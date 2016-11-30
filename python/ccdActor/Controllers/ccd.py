import logging

import fpga.ccd

class ccd(fpga.ccd.CCD):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        fpga.ccd.CCD.__init__(self, actor.ids.specNum, actor.ids.arm, site=actor.ids.site)
        self.actor = actor
        self.name = name
        
    def stop(self):
        pass
    def start(self):
        pass
    
