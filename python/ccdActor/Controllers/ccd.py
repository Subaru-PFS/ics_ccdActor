from __future__ import absolute_import
import logging

from ccdActor.main import SpectroIds

from . import fpga.ccd
reload(fpga.ccd)


class ccd(fpga.ccd.CCD):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        try:
            fakeCam = actor.config.get(actor.name, 'fakeCam')
            actor.bcast.warn('text="setting ccd up on the fake camera: %s"' % (fakeCam))
            ids = SpectroIds(fakeCam, actor.ids.site)
        except:
            ids = actor.ids
        
        fpga.ccd.CCD.__init__(self, ids.specNum, ids.arm, site=ids.site)
        self.actor = actor
        self.name = name
        
    def stop(self):
        pass
    def start(self):
        pass
    
