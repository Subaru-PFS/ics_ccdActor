from __future__ import absolute_import
from past.builtins import reload

import logging

import xcu_fpga.fee.feeControl as feeControl
reload(feeControl)

class fee(feeControl.FeeControl):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        feeControl.FeeControl.__init__(self, logLevel=logLevel)
        self.actor = actor
        self.name = name
        
    def stop(self, cmd=None):
        pass
    def start(self, cmd=None):
        pass
    
