#!/usr/bin/env python

import os

import opscore.protocols.keys as keys
import opscore.protocols.types as types
from opscore.utility.qstr import qstr

import fpga.ccdFuncs as ccdFuncs
reload(ccdFuncs)

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
            ('wipe', '[<nrows>] [<ncols>]', self.wipe),
            ('read', '@(bias|dark|flat|arc|object|junk) [<nrows>] [<ncols>]', self.read),
            ('clock','[<nrows>] <ncols>', self.clock),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
                                        keys.Key("nrows", types.Int(),
                                                 help='Number of rows to readout'),
                                        keys.Key("ncols", types.Int(),
                                                 help='Number of amp columns to readout'),
                                        
        )

        self.exposureState = 'idle'
        self.nrows = None
        self.ncols = None
        
    @property
    def ccd(self):
        return self.actor.ccd
    
    @property
    def fee(self):
        return self.actor.fee
    
    def wipe(self, cmd, doFinish=True, nrows=None, ncols=None):
        """ Wipe/flush the detector and put it in integration mode. """

        cmdKeys = cmd.cmd.keywords

        if nrows is None:
            nrows = cmdKeys['nrows'].values[0] if 'nrows' in cmdKeys else None
        if ncols is None:
            ncols = cmdKeys['ncols'].values[0] if 'ncols' in cmdKeys else None
        self.nrows = nrows 
        self.ncols = ncols
        
        cmd.inform('exposureState="wiping"')
        ccdFduncs.wipe(self.ccd, feeControl=self.fee,
                      nrows=self.nrows, ncols=self.ncols)
        cmd.inform('exposureState="integrating"')
        if doFinish:
            cmd.finish('text="wiped!"')

    def clock(self, cmd, doFinish=True, nrows=None, ncols=None):
        """ Start the detector clocking. """

        cmdKeys = cmd.cmd.keywords

        nrows = cmdKeys['nrows'].values[0] if 'nrows' in cmdKeys else None
        ncols = cmdKeys['ncols'].values[0]
        
        ccdFuncs.clock(ncols, nrows=nrows,
                       ccd=self.ccd, feeControl=self.fee,
                       cmd=cmd)
        
        if doFinish:
            cmd.finish('text="clocking!"')
        else:
            cmd.inform('text="clocking!"')

    def read(self, cmd, doFinish=True, nrows=None, ncols=None,
             doModes=True, doFeeCards=True):
        """ Readout the detector and put it in idle mode. """

        cmdKeys = cmd.cmd.keywords
        imtype = 'bias'

        if nrows is None:
            nrows = cmdKeys['nrows'].values[0] if 'nrows' in cmdKeys else None
            if nrows is None:
                nrows = self.nrows
        if ncols is None:
            ncols = cmdKeys['ncols'].values[0] if 'ncols' in cmdKeys else None
            if ncols is None:
                ncols = self.ncols

        def rowCB(line, image, errorMsg="OK", cmd=cmd, **kwargs):
            imageHeight = image.shape[0]
            everyNRows = 250
            if (line % everyNRows != 0) and (line < imageHeight-1):
                return
            cmd.inform('readRows=%d,%d' % (line, imageHeight))
            
        cmd.inform('exposureState="reading"')
        im, filepath = ccdFuncs.readout(imtype, self.ccd, feeControl=self.fee,
                                        nrows=nrows, ncols=ncols,
                                        doModes=doModes, doFeeCards=doFeeCards,
                                        rowStatsFunc=rowCB)

        dirname, filename = os.path.split(filepath)
        rootDir, dateDir = os.path.split(dirname)

        cmd.inform('exposureState="idle"')
        if doFinish:
            lastFunc = cmd.finish
        else:
            lastFunc = cmd.inform
        lastFunc('filepath=%s,%s,%s' % (qstr(rootDir),
                                        qstr(dateDir),
                                        qstr(filename)))
        
    def test1(self, cmd):
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
                                        nrows=10, ncols=100,
                                        rowStatsFunc=rowCB)

        dirname, filename = os.path.split(filepath)
        rootDir, dateDir = os.path.split(dirname)

        cmd.inform('exposureState="idle"')        
        cmd.finish('filepath=%s,%s,%s' % (qstr(rootDir),
                                          qstr(dateDir),
                                          qstr(filename)))
        

        
