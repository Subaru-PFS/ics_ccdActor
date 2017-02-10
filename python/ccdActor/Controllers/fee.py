from __future__ import absolute_import

import logging

import xcu_fpga.fee.feeControl as feeControl
reload(feeControl)

class fee(feeControl.FeeControl):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        feeControl.FeeControl.__init__(self, logLevel=logLevel)
        self.actor = actor
        self.name = name
        
    def stop(self):
        pass
    def start(self):
        pass
    
