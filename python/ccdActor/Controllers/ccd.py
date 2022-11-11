from importlib import reload

import logging

import fpga.ccd
from ics.utils.sps import spectroIds

reload(fpga.ccd)

class ccd(fpga.ccd.CCD):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG):

        self.actor = actor
        self.name = name

        fakeCam = actor.actorConfig.get('fakeCam', None)
        if fakeCam is not None:
            actor.bcast.warn('text="setting ccd up on the fake camera: %s"' % (fakeCam))
            ids = spectroIds.SpectroIds(partname=fakeCam, site=actor.ids.site)
        else:
            ids = actor.ids

        adcVersion = actor.actorConfig.get('adcVersion', None)
        if adcVersion is not None:
            actor.bcast.warn('text="overriding default FPGA/ADC type: %s"' % (adcVersion))

        fpga.ccd.CCD.__init__(self, ids.specNum, ids.arm, site=ids.site,
                              adcVersion=adcVersion)
        actor.bcast.inform('version_fpga="%s"; text="%s"' % (self.fpgaVersion(), self))

    def stop(self, cmd=None):
        pass

    def start(self, cmd=None):
        pass
