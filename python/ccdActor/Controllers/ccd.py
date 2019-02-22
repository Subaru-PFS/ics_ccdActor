from importlib import reload

import logging

import fpga.ccd
from pfscore import spectroIds

reload(fpga.ccd)

class ccd(fpga.ccd.CCD):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        self.actor = actor
        self.name = name
        try:
            fakeCam = actor.config.get(actor.name, 'fakeCam')
            actor.bcast.warn('text="setting ccd up on the fake camera: %s"' % (fakeCam))
            ids = spectroIds.SpectroIds(partname=fakeCam, site=actor.ids.site)
        except:
            ids = actor.ids

        fpga.ccd.CCD.__init__(self, ids.specNum, ids.arm, site=ids.site)

    def stop(self, cmd=None):
        pass

    def start(self, cmd=None):
        pass
