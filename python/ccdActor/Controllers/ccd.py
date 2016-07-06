import logging

import fpga.ccd

class ccd(fpga.ccd.CCD):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        dewarLet, specNum = actor.hostIds()
        
        fpga.ccd.CCD.__init__(self, specNum, dewarLet)
        self.actor = actor
        self.name = name
        
    def stop(self):
        pass
    def start(self):
        pass
    
