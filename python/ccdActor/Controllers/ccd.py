from importlib import reload

import logging

import fpga.ccd
from pfs.utils import spectroIds

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

        try:
            adcVersion = actor.config.get('fee', 'adcVersion')
            actor.bcast.warn('text="overriding default FPGA/ADC type: %s"' % (adcVersion))
        except:
            adcVersion = None

        fpga.ccd.CCD.__init__(self, ids.specNum, ids.arm, site=ids.site,
                              adcVersion=adcVersion)
        actor.bcast.inform('version_fpga="%s"; text="%s"' % (self.fpgaVersion(), self))

    def stop(self, cmd=None):
        pass

    def start(self, cmd=None):
        pass
