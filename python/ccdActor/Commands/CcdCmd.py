#!/usr/bin/env python

import os

import opscore.protocols.keys as keys
import opscore.protocols.types as types
from opscore.utility.qstr import qstr

import fpga.ccdFuncs as ccdFuncs

class CcdCmd(object):

    def __init__(self, actor):
        # This lets us access the rest of the actor.
        self.actor = actor

        # Declare the commands we implement. When the actor is started
        # these are registered with the parser, which will call the
        # associated methods when matched. The callbacks will be
        # passed a single argument, the parsed and typed command.
        #
        self.vocab = [
            ('wipe', '', self.wipe),
            ('read', '@(bias|dark|flat|arc|object)', self.read),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
        )

    @property
    def ccd(self):
        return self.actor.ccd
    
    @property
    def fee(self):
        return self.actor.fee
    
    def wipe(self, cmd):
        """ Wipe/flush the detector and put it in integration mode. """

        cmd.inform('exposureState="wiping"')
        ccdFuncs.wipe(self.ccd, feeControl=self.fee)
        cmd.inform('exposureState="integrating"')
        cmd.finish('text="wiped!"')

    def read(self, cmd):
        """ Readout the detector and put it in idle mode. """

        cmdKeys = cmd.cmd.keywords
        imtype = 'bias'

        def rowCB(line, image, errorMsg="OK", cmd=cmd, **kwargs):
            imageHeight = image.shape[0]
            everyNRows = 250
            if (line % everyNRows != 0) and (line < imageHeight-1):
                return
            cmd.inform('readRows=%d,%d' % (line, imageHeight))
            
        cmd.inform('exposureState="reading"')
        im, filepath = ccdFuncs.readout(imtype, self.ccd, feeControl=self.fee,
                                        rowStatsFunc=rowCB)

        dirname, filename = os.path.split(filepath)
        rootDir, dateDir = os.path.split(dirname)

        cmd.inform('exposureState="idle"')        
        cmd.finish('filepath=%s,%s,%s' % (qstr(rootDir),
                                          qstr(dateDir),
                                          qstr(filename)))
        

        
