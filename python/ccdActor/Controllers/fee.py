import logging
from importlib import reload

import xcu_fpga.fee.feeControl as feeControl

reload(feeControl)


class fee(feeControl.FeeControl):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        self.actor = actor
        self.name = name

        fpga = actor.controllers.get('ccd', None)
        port = actor.actorConfig['fee']['port']
        features = actor.actorConfig.get('feeFeatures', None)

        feeControl.FeeControl.__init__(self, fpga=fpga,
                                       port=port,
                                       features=features,
                                       logLevel=logLevel)
        self.grabStaticKeys()

    def grabStaticKeys(self, cmd=None):
        self.actor.bcast.inform('version_fee="%s"' % self.getCommandStatus('revision')['revision.FEE'])

        serialDict = self.getCommandStatus('serial')
        serialNames = ('FEE', 'ADC', 'PA0', 'CCD0', 'CCD1')
        serials = [serialDict[f"serial.{s}"] for s in serialNames]
        serialsKey = ','.join(serials)
        self.actor.bcast.inform(f'serials={serialsKey}')

    def stop(self, cmd=None):
        pass

    def start(self, cmd=None):
        pass
