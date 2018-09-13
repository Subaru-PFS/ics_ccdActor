#!/usr/bin/env python

from builtins import object
import argparse
import logging
import os
import socket

from twisted.internet import reactor

import actorcore.ICC

def ourIdent(hostname=None):
    pass

def hostnameId():
    hostname = socket.gethostname()
    hostname = os.path.splitext(hostname)[0]
    _, hostid = hostname.split('-')
    return hostid

class SpectroIds(object):
    validArms = {'b', 'r', 'n'}
    validSites = {'J','L','S','X'}
    
    def __init__(self, dewarName=None, site=None):
        if dewarName is None:
            dewarName = hostnameId()
        if len(dewarName) != 2:
            raise RuntimeError('dewarName (%s) must be of the form "r1"' % (dewarName))
        
        if dewarName[0] not in self.validArms:
            raise RuntimeError('arm (%s) must one of: %s' % (dewarName[0], self.validArms))
        if dewarName[1] not in ('1','2','3','4','5','6','7','8','9'):
            raise RuntimeError('spectrograph number (%s) must be in 1..9' % (dewarName[1]))
        self.dewarName = dewarName
        
        if site is None:
            import os
            site = os.environ['PFS_SITE']
            
        if site not in self.validSites:
            raise RuntimeError('site (%s) must one of: %s' % (site, self.validSites))
        self.site = site

    def __str__(self):
        return "SpectroIds(cam=%s arm=%s spec=%s)" % (self.cam, self.arm, self.specModule)
        
    @property
    def cam(self):
        return self.dewarName

    @property
    def camNum(self):
        return '%d%d' % (self.specNum,
                         self.validArms[self.arm])
    @property
    def arm(self):
        return self.dewarName[0]

    @property
    def specNum(self):
        return int(self.dewarName[1])

    @property
    def specModule(self):
        return 'sm' + self.dewarName[1]

    @property
    def idDict(self):
        _idDict = dict(cam=self.cam,
                       camNum=self.camNum,
                       site=self.site,
                       arm=self.arm,
                       specNum=self.specNum,
                       spec=self.specModule)
        return _idDict
    
class OurActor(actorcore.ICC.ICC):
    def __init__(self, name=None, site=None,
                 productName=None, configFile=None,
                 logLevel=30):

        """ Setup an Actor instance. See help for actorcore.Actor for details. """

        if name is not None:
            cam = name.split('_')[-1]
        else:
            cam = None
        self.ids = SpectroIds(cam, site)

        if name is None:
            name = 'ccd_%s' % (self.ids.cam)
            
        # This sets up the connections to/from the hub, the logger, and the twisted reactor.
        #

        actorcore.ICC.ICC.__init__(self, name, 
                                   productName=productName, 
                                   configFile=configFile)
        self.logger.setLevel(logLevel)
        self.everConnected = False

        self.monitors = dict()
        self.statusLoopCB = self.statusLoop

        self.exposure = None
        
    @property
    def fee(self):
        return self.controllers['fee']

    @property
    def ccd(self):
        return self.controllers['ccd']

    def specIds(self):
        return self.ids.arm, self.ids.specNum
        

    def connectionMade(self):
        if self.everConnected is False:
            logging.info("Attaching all controllers...")
            self.allControllers = [s.strip() for s in self.config.get(self.name, 'startingControllers').split(',')]
            self.attachAllControllers()
            self.everConnected = True

            models = [m % self.ids.idDict for m in ('enu', 'dcb',
                                                    'xcu_%(cam)s', 'ccd_%(cam)s',
                                                    'enu_%(spec)s', 'dcb_%(spec)s',)]
            self.logger.info('adding models: %s', models)
            self.addModels(models)
            self.logger.info('added models: %s', self.models.keys())

            
    def statusLoop(self, controller):
        try:
            self.callCommand("%s status" % (controller))
        except:
            pass
        
        if self.monitors.setdefault(controller, 0) > 0:
            reactor.callLater(self.monitors[controller],
                              self.statusLoopCB,
                              controller)
            
    def monitor(self, controller, period, cmd=None):
        running = self.monitors.setdefault(controller, 0) > 0
        self.monitors[controller] = period

        if (not running) and period > 0:
            cmd.warn('text="starting %gs loop for %s"' % (self.monitors[controller],
                                                          controller))
            self.statusLoopCB(controller)
        else:
            cmd.warn('text="adjusted %s loop to %gs"' % (controller, self.monitors[controller]))
#
# To work
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=None, type=str, nargs='?',
                        help='configuration file to use')
    parser.add_argument('--logLevel', default=logging.INFO, type=int, nargs='?',
                        help='logging level')
    parser.add_argument('--name', default=None, type=str, nargs='?',
                        help='ccd name, e.g. ccd_r1')
    parser.add_argument('--site', default=None, type=str, nargs='?',
                        help='PFS site, e.g. L for LAM')
    args = parser.parse_args()
    
    theActor = OurActor(args.name,
                        productName='ccdActor',
                        site=args.site,
                        configFile=args.config,
                        logLevel=args.logLevel)
    theActor.run()

if __name__ == '__main__':
    main()
