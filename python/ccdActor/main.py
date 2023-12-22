#!/usr/bin/env python

import argparse
import logging

import actorcore.ICC
import pfs.utils.butler as pfsButler

from ics.utils.sps import spectroIds
from twisted.internet import reactor


class OurActor(actorcore.ICC.ICC):
    def __init__(self, name=None, site=None,
                 productName=None,
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

        try:
            actorcore.ICC.ICC.__init__(self, name,
                                       productName=productName,
                                       idDict=self.ids.idDict)
        except Exception as e:
            print(f'ICC initialization failed: {e}')
            print(f'   actorConfig: {self.actorConfig}')
        self.logger.setLevel(logLevel)
        logging.getLogger('cmdr').setLevel(20)
        self.logger.info(f'actorConfig: {self.actorConfig}')
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

    @property
    def ccdModelName(self):
        return 'ccd_%(camName)s' % self.ids.idDict

    @property
    def ccdModel(self):
        return self.models[self.ccdModelName]

    @property
    def xcuModel(self):
        xcuName = 'xcu_%(camName)s' % self.ids.idDict
        return self.models[xcuName]

    def connectionMade(self):
        if self.everConnected is False:
            models = [m % self.ids.idDict for m in ('gen2', 'iic', 'pfilamps', 'dcb', 'dcb2',
                                                    'sps', 'scr',
                                                    'ccd_%(camName)s', 'xcu_%(camName)s',
                                                    'enu_%(specName)s')]
            self.logger.info('adding models: %s', models)
            self.addModels(models)
            self.logger.info('added models: %s', self.models.keys())
            self.butler = pfsButler.Butler(specIds=self.ids)

            logging.info("Attaching all controllers...")
            self.allControllers = self.actorConfig['controllers']['starting']
            self.attachAllControllers()
            self.everConnected = True

    def reloadConfiguration(self, cmd):
        """ optional user hook, called from Actor._reloadConfiguration"""
        pass

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
                        logLevel=args.logLevel)
    theActor.run()


if __name__ == '__main__':
    main()
