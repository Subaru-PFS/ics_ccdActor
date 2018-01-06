#!/usr/bin/env python

from __future__ import division, absolute_import, print_function
from past.builtins import reload

import functools

import opscore.protocols.keys as keys
import opscore.protocols.types as types

import fpga.ccdFuncs as ccdFuncs
reload(ccdFuncs)

import astropy.io.fits as pyfits

import Commands.exposure as exposure
reload(exposure)
    
class CcdCmd(object):
    imTypes = {'bias', 'dark', 'flat', 'arc', 'object'}
    
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
            ('read',
             '[@(bias|dark|flat|arc|object|junk)] [<nrows>] [<ncols>] [<exptime>] [<darktime>] [<obstime>] [<comment>] [@nope]',
             self.read),
            ('clock','[<nrows>] <ncols>', self.clock),
            ('revread','[<nrows>] [<binning>]', self.revRead),
            ('clearExposure', '', self.clearExposure),
            ('expose', '<nbias>', self.exposeBiases),
            ('expose', '<darks>', self.exposeDarks),
            ('setOffset', '<offset> <value>', self.setOffset),
            ('setOffsets', '<filename>', self.setOffsets),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
                                        keys.Key("nrows", types.Int(),
                                                 help='Number of rows to readout'),
                                        keys.Key("ncols", types.Int(),
                                                 help='Number of amp columns to readout'),
                                        keys.Key("binning", types.Int(),
                                                 help='number of rows to bin'),
                                        keys.Key("filename", types.String(),
                                                 help='the name of a file to load from.'),
                                        keys.Key("obstime", types.String(),
                                                 help='official DATE-OBS string'),
                                        keys.Key("exptime", types.Float(),
                                                 help='official EXPTIME'),
                                        keys.Key("darktime", types.Float(),
                                                 help='official EXPTIME'),
                                        keys.Key("comment", types.String(),
                                                 help='a comment to add.'),
                                        keys.Key("nbias", types.Int(),
                                                 help='number of biases to take'),
                                        keys.Key("darks", types.Float()*(1,),
                                                 help='list of dark times to take'),
                                        keys.Key("offset",
                                                 types.Int(),
                                                 types.Int(),
                                                 types.String(),
                                                 help='offset value'),
                                        keys.Key("value", types.Float(),
                                                 help='offset value'),
        )

        self.exposureState = 'idle'
        self.nrows = None
        self.ncols = None

        self.actor.exposure = None

        self.initCallbacks()

    @property
    def ccd(self):
        return self.actor.ccd
    
    @property
    def fee(self):
        return self.actor.fee

    def initCallbacks(self):
        """ """

        pass

    def _setExposure(self, cmd, exp, doForce=False):
        if self.actor.exposure is not None:
            if not doForce:
                raise exposure.ExposureIsActive('an exposure is already active: %s' % (self.actor.exposure))
            self.actor.exposure.abort(cmd)
        self.actor.exposure = exp

    def _getExposure(self, cmd):
        if self.actor.exposure is None:
            raise exposure.NoExposureIsActive('no exposure is active!!')
            
        return self.actor.exposure

    def closeoutExposure(self, cmd):
        self.actor.exposure = None
    
    def clearExposure(self, cmd):
        cmd.warn('text="clearing running/broken exposure: %s"' % (self.actor.exposure))
        self.closeoutExposure(cmd)
        cmd.finish()

    def wipe(self, cmd, nrows=None, ncols=None, doFinish=True):
        """ Wipe/flush the detector and put it in integration mode. """

        cmdKeys = cmd.cmd.keywords

        if nrows is None:
            nrows = cmdKeys['nrows'].values[0] if 'nrows' in cmdKeys else None
        if ncols is None:
            ncols = cmdKeys['ncols'].values[0] if 'ncols' in cmdKeys else None
        self.nrows = nrows 
        self.ncols = ncols

        ## NOT using nrows, ncols yet!
        exp = exposure.Exposure(self.actor, None, 0,
                                self.ccd, self.fee,
                                self.actor.bcast)
        self._setExposure(cmd, exp)

        exp.wipe(cmd=cmd, nrows=nrows)

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
            cmd.finish('text="clock!"')
        else:
            cmd.inform('text="clock!"')

    def revRead(self, cmd, doFinish=True, nrows=None, ncols=None):
        """ Start the detector clocking. """

        cmdKeys = cmd.cmd.keywords

        nrows = cmdKeys['nrows'].values[0] if 'nrows' in cmdKeys else None
        rowBinning = cmdKeys['binning'].values[0] if 'binning' in cmdKeys else 10
        
        ccdFuncs.fastRevRead(ccd=self.actor.ccd,
                             rowBinning=rowBinning, nrows=nrows)

        if doFinish:
            cmd.finish('text="revread"')
        else:
            cmd.inform('text="revread"')

    def read(self, cmd, imType=None, doFinish=True,
             nrows=None, ncols=None,
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

        if imtype is None:
            imtype = 'test'
            for t in self.imTypes:
                if t in cmdKeys:
                    imtype = t

        doRun = 'nope' not in cmdKeys
        comment = cmdKeys['comment'].values[0] if 'comment' in cmdKeys else ''
        exptime = cmdKeys['exptime'].values[0] if 'exptime' in cmdKeys else None
        darktime = cmdKeys['darktime'].values[0] if 'darktime' in cmdKeys else None

        try:
            exp = self._getExposure(cmd)
        except exposure.NoExposureIsActive:
            exp = exposure.Exposure(self.actor, None, 0,
                                    self.ccd, self.fee,
                                    self.actor.bcast)
            self._setExposure(cmd, exp)

        exp.readout(imtype, exptime, darkTime=darktime,
                    nrows=nrows, ncols=ncols,
                    doFeeCards=doFeeCards, doModes=doModes,
                    comment=comment, doRun=doRun, cmd=cmd)
        self.closeoutExposure(cmd=cmd)
        
        if doFinish:
            cmd.finish()

    def _nextExposure(self, cmd, runningExp, exposures, idx):
        cmd.inform('text="calling for exposure %d of %s"' % (idx+1, exposures))
        if idx >= len(exposures) or (runningExp is not None and runningExp.pleaseStop):
            self.closeoutExposure(cmd)
            cmd.finish()
            return

        if runningExp is not None and runningExp != self.actor.exposure:
            cmd.warn('text="abandoning orphan sequence"')
            cmd.finish()
            return

        if runningExp == self.actor.exposure:
            self.closeoutExposure(cmd)

        thisType, thisExpTime, comment = exposures[idx]
        cmd.inform('text="starting %d of %d: %s, %0.2f sec"' % (idx+1, len(exposures),
                                                                thisType, thisExpTime))
        newExp = exposure.Exposure(self.actor, thisType, thisExpTime,
                                   self.ccd, self.fee, cmd=cmd, comment=comment)
        self._setExposure(cmd, newExp)
        newExp.run(callback=functools.partial(self._nextExposure, cmd, newExp, exposures, idx+1))

    def exposeBiases(self, cmd):
        """ Take a number of complete biases. """

        cmdKeys = cmd.cmd.keywords
        nbias = cmdKeys['nbias'].values[0] if 'nbias' in cmdKeys else 1
        comment = cmdKeys['comment'].values[0] if 'comment' in cmdKeys else ''

        expList = [('bias',0,comment) for i in range(nbias)]
        self._nextExposure(cmd, None, expList, 0)

    def exposeDarks(self, cmd):
        """ Take a list of complete darks. """

        cmdKeys = cmd.cmd.keywords
        darks = cmdKeys['darks'].values
        comment = cmdKeys['comment'].values[0] if 'comment' in cmdKeys else ''

        expList = []
        for i, expTime in enumerate(darks):
            if expTime < 0:
                cmd.warn('text="NOT taking dark %d of %d: invalid time: %0.2f sec"' % (i+1, len(darks), expTime))
                continue
            expType = 'dark' if expTime > 0 else 'bias'
            expList.append((expType, expTime, comment),)

        self._nextExposure(cmd, None, expList, 0)

    def setOffset(self, cmd):
        """ Set a single offset. """

        channel,amp,side = cmd.cmd.keywords['offset'].values
        value = cmd.cmd.keywords['value'].values[0]

        self.actor.fee.setOffsets([channel*4 + amp], [value], leg=side)

        cmd.finish('text="set ch%d/%d/%s = %s"' % (channel, amp, side, value))

    def setOffsets(self, cmd):
        """ Load the FEE with config saved in the existing image file. """

        filename = cmd.cmd.keywords['filename'].values[0]
        fee = self.actor.fee

        hdr = pyfits.getheader(filename)
        plist = []
        nlist = []
        clist = []
        for c in 0,1:
            for p in range(4):
                chan = 'offset.ch%d.%d' % (c, p)
                pval = hdr['%sp' % (chan)]
                nval = hdr['%sn' % (chan)]
                clist.append(c*4 + p)
                plist.append(pval)
                nlist.append(nval)

        fee.setOffsets(clist, plist, leg='p')
        fee.setOffsets(clist, nlist, leg='n')

        cmd.finish('text="set!"')

