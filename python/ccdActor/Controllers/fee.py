from importlib import reload
import logging

import xcu_fpga.fee.feeControl as feeControl
reload(feeControl)

class fee(feeControl.FeeControl):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        fpga = actor.controllers.get('ccd', None)
        port = actor.config.get('fee', 'port')
        feeControl.FeeControl.__init__(self, fpga=fpga,
                                       port=port,
                                       logLevel=logLevel)
        self.actor = actor
        self.name = name
        
    def stop(self, cmd=None):
        pass
    def start(self, cmd=None):
        pass
    
