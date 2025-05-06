#!/usr/bin/env python

from importlib import reload

import functools

import opscore.protocols.keys as keys
import opscore.protocols.types as types

import astropy.io.fits as pyfits

import fpga.ccdFuncs as ccdFuncs
from clocks import clockIDs

import Commands.exposure as exposure

reload(clockIDs)
reload(ccdFuncs)
reload(exposure)
    
class CcdCmd(object):
    imTypes = {'bias', 'dark', 'flat', 'arc', 'object', 'domeflat', 'test'}
    
    def __init__(self, actor):
        # This lets us access the rest of the actor.
        self.actor = actor

        # Declare the commands we implement. When the actor is started
        # these are registered with the parser, which will call the
        # associated methods when matched. The callbacks will be
        # passed a single argument, the parsed and typed command.
        #
        self.vocab = [
            ('wipe', '[<nrows>] [<ncols>] [@fast]', self.wipe),
            ('read',
             '[@(bias|dark|flat|arc|object|domeflat|test|junk)] [<nrows>] [<ncols>] [<visit>] '
             '[<exptime>] [<darktime>] [<obstime>] [<comment>] [@nope] [@swoff] [@fast] [<row0>] '
             '[<pfsDesign>] [<metadata>]',
             self.read),
            ('erase', '', self.erase),
            ('clock','[<nrows>] <ncols>', self.clock),
            ('revread','[<nrows>] [<binning>]', self.revRead),
            ('clearExposure', '', self.clearExposure),
            ('expose', '<nbias>', self.exposeBiases),
            ('expose', '<darks>', self.exposeDarks),
            ('setOffset', '<offset> <value>', self.setOffset),
            ('setOffsets', '<filename>', self.setOffsets),
            ('controlLVDS', '@(on|off)', self.controlLVDS),
            ('readCtrlWord', '', self.readCtrlWord),
            ('setClocks', '[<on>] [<off>]', self.setClocks),
            ('holdClocks', '[<on>] [<off>]', self.holdClocks),
            ('setAdcMode', '@(msb|mid|lsb)', self.setAdcMode),
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
                                        keys.Key("visit", types.Int(),
                                                 help='PFS visit to ass ign to filename'),
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
                                        keys.Key("on",
                                                 types.Enum(*sorted([c.label for c in clockIDs.signals]))*(1,),
                                                 help="signals to turn on"),
                                        keys.Key("off", types.Enum(*sorted([c.label for c in clockIDs.signals]))*(1,),
                                                 help="signals to turn off"),
                                        keys.Key("row0", types.Int(),
                                                 help='first row of band to read'),
                                        keys.Key("pfsDesign",
                                                 types.Long(), types.String(),
                                                 help='the pfsDesignId and name to use'),
                                        keys.Key("metadata",
                                                 types.Int()*3,
                                                 types.String()*4,
                                                 help='header stuffers from iic and gen2'),
                                        )

        self.exposureState = 'idle'
        self.nrows = None
        self.ncols = None

        self.actor.exposure = None

        self.initCallbacks()

        self.genStatus()

    @property
    def ccd(self):
        return self.actor.ccd
    
    @property
    def fee(self):
        return self.actor.fee

    def genStatus(self, cmd=None):
        if cmd is None:
            cmd = self.actor.bcast

        if self.actor.exposure is None:
            exposure.Exposure.genStatus(cmd)
        else:
            self.exposure.genStatus()

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
        """Remove state of any existing/broken exposure. Also set FEE to idle. """

        cmd.warn('text="clearing running/broken exposure: %s"' % (self.actor.exposure))
        if self.actor.exposure is not None:
            self.actor.exposure.finish()
        else:
            self.actor.fee.setMode('idle')
        self.closeoutExposure(cmd)
        cmd.finish()

    def erase(self, cmd):
        exp = exposure.Exposure(self.actor, None, 0,
                                self.ccd, self.fee,
                                self.actor.bcast)
        exp.simpleWipe(cmd=cmd)
        cmd.finish()

    def wipe(self, cmd, nrows=None, ncols=None, doFinish=True):
        """ Wipe/flush the detector and put it in integration mode. """

        cmdKeys = cmd.cmd.keywords

        fast = 'fast' in cmdKeys
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

        exp.wipe(cmd=cmd, nrows=nrows, fast=fast)

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

    def read(self, cmd, imtype=None, doFinish=True,
             nrows=None, ncols=None,
             doModes=True, doFeeCards=False):
        """ Readout the detector and put it in idle mode. """

        cmdKeys = cmd.cmd.keywords

        row0 = cmdKeys['row0'].values[0] if 'row0' in cmdKeys else 0
        if row0 > 0 and 'nrows' not in cmdKeys:
            cmd.fail('text="if row0 is specified, nrows must also be"')
            return

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
                    break

        doRun = 'nope' not in cmdKeys
        comment = cmdKeys['comment'].values[0] if 'comment' in cmdKeys else ''
        exptime = cmdKeys['exptime'].values[0] if 'exptime' in cmdKeys else None
        obstime = cmdKeys['obstime'].values[0] if 'obstime' in cmdKeys else None
        darktime = cmdKeys['darktime'].values[0] if 'darktime' in cmdKeys else None
        visit = cmdKeys['visit'].values[0] if 'visit' in cmdKeys else None
        pfsDesign = cmdKeys['pfsDesign'].values if 'pfsDesign' in cmdKeys else None
        metadata = cmdKeys['metadata'].values if 'metadata' in cmdKeys else None
        swOffTweak = 'swoff' in cmdKeys
        fast = 'fast' in cmdKeys

        try:
            exp = self._getExposure(cmd)
        except exposure.NoExposureIsActive:
            exp = exposure.Exposure(self.actor, None, 0,
                                    self.ccd, self.fee,
                                    self.actor.bcast)
            self._setExposure(cmd, exp)

        try:
            if self.ccd.holdOn or self.ccd.holdOff:
                cmd.warn(f'text="reading with held clocks: on={self.ccd.holdOn} off={self.ccd.holdOff}"')
        except AttributeError:
            pass                # Old ADC code (7.40) does not have the attribute.

        if swOffTweak:
            cmd.warn('text="disabling SW on CCD1, to identify CCD amps."')
            exp.setFee(ccdFuncs.disableSWOnCcdTweak(exp.fee), cmd)

        if row0 > 0:
            cmd.warn(f'text="wiping {row0} rows"')
            exp.wipe(cmd=cmd, nrows=row0, fast=True)

        exp.readout(imtype, exptime, darkTime=darktime,
                    visit=visit, obstime=obstime,
                    nrows=nrows, ncols=ncols, row0=row0,
                    doFeeCards=doFeeCards, doModes=doModes,
                    pfsDesign=pfsDesign, metadata=metadata,
                    comment=comment, doRun=doRun, fast=fast, cmd=cmd)

        if row0 > 0:
            haveReadTo = row0 + nrows
            rowsLeft = self.ccd.nrows - haveReadTo
            cmd.warn(f'text="wiping {rowsLeft} rows after the {haveReadTo} row window"')
            exp.simpleWipe(cmd=cmd, nrows=rowsLeft, fast=True)

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

    def controlLVDS(self, cmd):
        """ Enable or disable the LVDS drivers to the FEE. """
        
        onOff = 'on' in cmd.cmd.keywords

        if onOff:
            ret = self.ccd.enableLVDS()
        else:
            ret = self.ccd.disableLVDS()

        cmd.finish('text="last=%s set=%s"' % (ret, onOff))
        
    def readCtrlWord(self, cmd):
        """ Read the PCI R_WPU_CTRL word. """
        
        cmd.finish('text="R_WPU_CTRL=0x%08x"' % (self.ccd.readCtrlWord()))

    def setAdcMode(self, cmd):
        """ Set the ADC readout mode (msb, lsb, or mid) """

        mode = 'default'
        for m in {'msb', 'mid', 'lsb'}:
            if m in cmd.cmd.keywords:
                mode = m
                break

        self.ccd.setAdcType(mode)
        cmd.finish(f'text="configured ADC mode {mode}: {str(self.ccd)}"')

    def setClocks(self, cmd):
        """ Set/clear given clock lines. """

        cmdKeys = cmd.cmd.keywords

        turnOn = []
        if 'on' in cmdKeys:
            turnOn = [clockIDs.signalsByName[n] for n in cmdKeys['on'].values]
        turnOff = []
        if 'off' in cmdKeys:
            turnOff = [clockIDs.signalsByName[n] for n in cmdKeys['off'].values]
        
        self.ccd.setClockLevels(turnOn=turnOn, turnOff=turnOff, cmd=cmd)

        cmd.finish()
        
    def holdClocks(self, cmd):
        """ request that given clock lines always be help on or off """

        cmdKeys = cmd.cmd.keywords

        holdOn = []
        if 'on' in cmdKeys:
            holdOn = cmdKeys['on'].values
        holdOff = []
        if 'off' in cmdKeys:
            holdOff = cmdKeys['off'].values
        
        self.ccd.holdClocks(holdOn=holdOn, holdOff=holdOff, cmd=cmd)

        cmd.finish(f'text="set held clocks. on={self.ccd.holdOn} off={self.ccd.holdOff}"')
        
        
