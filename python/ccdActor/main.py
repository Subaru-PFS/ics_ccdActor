#!/usr/bin/env python

import argparse
import logging
import os
import socket

from twisted.internet import reactor

import actorcore.ICC
from pfscore import spectroIds

class OurActor(actorcore.ICC.ICC):
    def __init__(self, name=None, site=None,
                 productName=None, configFile=None,
                 logLevel=30):

        """ Setup an Actor instance. See help for actorcore.Actor for details. """

        if name is not None:
            cam = name.split('_')[-1]
        else:
            cam = None

        self.ids = spectroIds.SpectroIds(cam, site)

        if name is None:
            name = 'ccd_%s' % (self.ids.camName)
            
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
        self.grating = 'real'
        
    @property
    def fee(self):
        return self.controllers['fee']

    @property
    def ccd(self):
        return self.controllers['ccd']

    @property
    def enuModel(self):
        enuName = 'enu_%(specName)s' % self.ids.idDict
        return self.models[enuName]
    
    def connectionMade(self):
        if self.everConnected is False:
            logging.info("Attaching all controllers...")
            self.allControllers = [s.strip() for s in self.config.get(self.name, 'startingControllers').split(',')]
            self.attachAllControllers()
            self.everConnected = True

            models = [m % self.ids.idDict for m in ('xcu_%(camName)s', 'ccd_%(camName)s',
                                                    'enu_%(specName)s', 'dcb_%(specName)s',)]
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
    parser.add_argument('--cam', default=None, type=str, nargs='?',
                        help='ccd name, e.g. r1')
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
