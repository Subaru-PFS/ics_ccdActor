from importlib import reload

import logging
import pathlib
import time
import threading

import numpy as np

import fitsio
from ics.utils.fits import wcs
from ics.utils.fits import mhs as fitsMhs
from ics.utils.fits import utils as fitsUtils
from ics.utils.fits import timecards
from ics.utils.sps import fits as spsFits
import ics.utils.time as pfsTime
from opscore.utility.qstr import qstr
import fpga.ccdFuncs as ccdFuncs
import ccdActor.utils.basicQA as basicQA

reload(fitsMhs)
reload(fitsUtils)
reload(spsFits)
reload(pfsTime)

class ExposureIsActive(Exception):
    pass
class NoExposureIsActive(Exception):
    pass

class ExpThread(threading.Thread):
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs=None, verbose=None):
        threading.Thread.__init__(self, group=group, target=target, name=name)

        self.args = args
        self.kwargs = kwargs
        return

    def run(self):
        exp = self.kwargs['exp']
        callback = self.kwargs['callback']

        exp.cmd.inform('text="integrating for %0.2f s..."' % (exp.expTime))
        if exp.expTime > 0:
            time.sleep(exp.expTime)
        exp.readout()
        exp.cmd.inform('text="calling next exposure..."')
        callback()

class Exposure(object):
    exposureState = 'idle'

    def __init__(self, actor, imtype, expTime, ccd, fee, cmd=None, comment=''):
        self.actor = actor
        self.ccd = ccd
        self.fee = fee
        self.cmd = cmd
        self.imtype = imtype
        self.expTime = expTime
        self.startTime = time.time()
        self.comment = comment
        self.exposureState = "idle"
        self.logger = logging.getLogger('exposure')
        self.timecards = None
        self.headerCards = None
        self.obstime = None
        self.genStatus = self.__instanceGetStatus

        self.pleaseStop = False

    def __str__(self):
        return "Exposure(imtype=%s, expTime=%s, startedAt=%s)" % (self.imtype,
                                                                  self.expTime,
                                                                  self.startTime)
    def setFee(self, newFee, cmd):
        self.fee = newFee
        cmd.warn('text="replacing FEE instance for some reason."')

    @classmethod
    def genStatus(self_or_cls, cmd, state=None):
        """Generate any status keywords.

        Callable as class or instance method.

        Args
        ----
        self_or_cls : *either* self or cls
          Something which has our state variables.
        cmd : actorcore.Command
          where to send status keys
        """

        if state is None:
            state = self_or_cls.exposureState

        if state == 'aborted':
            cmd.warn('exposureState=%s' % (state))
        else:
            cmd.inform('exposureState=%s' % (state))

    def __instanceGetStatus(self, cmd=None, state=None):
        """Generate any status keywords.

        Only useable as instance method.
        """
        if cmd is None:
            cmd = self.cmd
        self.__class__.genStatus(cmd=cmd, state=state)

    def _setExposureState(self, newState, cmd=None):
        if cmd is None:
            cmd = self.cmd
        self.exposureState = newState
        self.genStatus(cmd, newState)

    def run(self, callback=None):
        if self.exposureState != 'idle':
            raise ExposureIsActive('this exposure is already running: %s' % (self))

        expThread = ExpThread(kwargs=dict(exp=self, callback=callback))
        expThread.daemon = True

        self.wipe()
        expThread.start()
        self.cmd.inform('text="fired off thread. active: %d"' % (threading.active_count()))

    def abort(self, abortCmd):
        abortCmd.warn('text="overwriting existing exposure!!!: %s"' % (self))
        self.fee.setMode('idle')
        self._setExposureState('aborted')
        self.cmd.fail('exposureState="aborted"')

    def finish(self):
        if self.exposureState != 'idle':
            self.cmd.warn('text="stopping a non-idle exposure: %s"' % (str(self)))
            self.fee.setMode('idle')
        self._setExposureState('idle')

    def simpleWipe(self, cmd=None, nrows=None, fast=False):
        """ Wipe/flush the detector, but leave it in idle mode."""

        if fast:
            cmd.inform('text="fast wipe"')

        ccdFuncs.wipe(self.ccd, feeControl=self.fee,
                      nwipes=1, nrows=nrows,
                      toExposeMode=False, blockPurgedWipe=fast)
        self.fee.setMode('idle')
        self._setExposureState('idle', cmd=cmd)

    def wipe(self, cmd=None, nrows=None, fast=False):
        """ Wipe/flush the detector and put it in integration mode. """

        if fast:
            cmd.inform('text="fast wipe"')
        self._setExposureState('wiping', cmd=cmd)

        nwipes = int(nrows != 0)
        if nwipes == 0:
            cmd.warn('text="not really wiping, because nrows=0..."')
        ccdFuncs.wipe(self.ccd, feeControl=self.fee,
                      nwipes=nwipes, nrows=nrows, blockPurgedWipe=fast)
        self.timecards = timecards.TimeCards()
        self._setExposureState('integrating', cmd=cmd)
        self.startTime = time.time()
        if nwipes > 0:
            self.startHeader(cmd)

    def armNum(self, cmd):
        """Return the correct arm number: 1, 2, or 4. 

        For the red cryostats, we have two arm numbers: 2 for low res,
        and 4 for medium res. This number is used (only?) in the
        filename. Resolve which to use.

        We _want_ to use the dcbActor rexm keyword. But we also allow
        manually overriding that from the self.actor.grating
        variable. That may only ever be used for code testing.

        """

        if self.actor.ids.arm != 'r':
            return self.actor.ids.armNum
        if self.actor.grating != 'real':
            arms = dict(low=2, med=4)
            cmd.warn(f'text="using fake grating position {self.actor.grating}"')
            return arms[self.actor.grating]

        try:
            rexm = self.actor.enuModel.keyVarDict['rexm'].getValue()
        except Exception as e:
            self.logger.warn('failed to get enu grating position: %s', e)
            cmd.warn('text="failed to get enu grating position: using low"')
            return 2

        try:
            # ENU uses "mid", which I think should be changed.
            arms = dict(low=2, mid=4, med=4)
            return arms[rexm]
        except KeyError:
            cmd.warn(f'text="enu grating position invalid ({rexm}), using low for filename"')
            return 2

    def arm(self, cmd):
        """Return the correct arm: 'b', 'r', 'm', 'n'.

        For the red cryostats, we have two arms: 'r' for low res,
        and 'm' for medium res. See .armNum() for details on how this is resolved.

        """
        arms = {1:'b', 2:'r', 3:'n', 4:'m'}
        armNum = self.armNum(cmd)
        return arms[armNum]

    def makeFilePath(self, visit, cmd=None):
        """ Fetch next image filename.

        In real life, we will instantiate a Subaru-compliant image pathname generating object.

        """

        armNum = self.armNum(cmd)
        path = self.actor.butler.getPath('spsFile', visit=visit, armNum=armNum)
        cmd.debug(f'text="path for {visit}: {path}"')
        pathDir = path.parent
        pathDir.mkdir(mode=0o2755, parents=True, exist_ok=True)
        return path

    def placeRows(self, subIm, row0):
        """Return a full-sized readout with the given band of rows copied in.

        Args
        ----
        subIm : np.array
          a partial readout
        row0 : `int`
          the detector row corresponding to the bottom of the subIm.

        Returns
        -------
        im : a full-size detector image, with subIm placed between rows row0..row0+nrows-1, and
             the rest of the image set to 0.
        """

        nrows = subIm.shape[0]

        newIm = self.ccd.makeEmptyImage()
        newIm[row0:row0+nrows,:] = subIm
        return newIm

    def readout(self, imtype=None, expTime=None, darkTime=None,
                visit=None, obstime=None, comment='',
                doFeeCards=True, doModes=True, fast=False,
                nrows=None, ncols=None, row0=0,
                cmd=None, doRun=True):
        if imtype is not None:
            self.imtype = imtype
        if expTime is not None:
            self.expTime = expTime
        if obstime is not None:
            self.obstime = obstime
        if comment is not None:
            self.comment = comment

        if row0 > 0 and nrows is None:
            raise RuntimeError("if row0 is specified, nrows must also be.")

        # In operations, we are always told what our visit is. If we
        # are not told, use an internally tracked file counter. Since we
        # also need to run the ccd readout code outside of the actor,
        # that is maintained by the ccd object.
        if visit is None:
            visit = self.ccd.fileMgr.consumeNextSeqno()

        if cmd is None:
            cmd = self.cmd

        def rowCB(line, image, errorMsg="OK", cmd=cmd, **kwargs):
            imageHeight = image.shape[0]
            everyNRows = 500
            if (line % everyNRows != 0) and (line < imageHeight-1):
                return
            cmd.inform('readRows=%d,%d' % (line, imageHeight))

        if self.exposureState != 'integrating':
            cmd.warn('text="reading out detector in odd state: %s"' % (str(self)))
        if self.headerCards is None and row0 == 0:
            self.startHeader(cmd)
        if self.timecards is None:
            self.timecards = timecards.TimeCards()

        self._setExposureState('reading', cmd=cmd)
        if expTime is None:
            self.expTime = time.time() - self.startTime
        # If we are not told what our dark time is, guess that the exposure was not
        # paused.
        if darkTime is None:
            if self.expTime == 0:
                darkTime = 0.0
            else:
                darkTime = self.expTime + 2*0.38  # Educated guess about shutter transit times.
        self.darkTime = darkTime

        if doRun:
            self.timecards.end(expTime=self.expTime)
            im, _ = ccdFuncs.readout(self.imtype, expTime=self.expTime,
                                     darkTime=self.darkTime,
                                     ccd=self.ccd, feeControl=self.fee,
                                     nrows=nrows, ncols=ncols,
                                     doFeeCards=False, doModes=doModes,
                                     comment=self.comment,
                                     doSave=False,
                                     rowStatsFunc=rowCB)
            if nrows is None:
                nrows = im.shape[0]
            im = self.fixupImage(im, cmd)

            if row0 > 0:
                im = self.placeRows(im, row0)

            filepath = self.makeFilePath(visit, cmd)
            
            addCards = []
            addCards.append(dict(name='W_CDROW0', value=row0,
                                comment='first row of readout window'))
            addCards.append(dict(name='W_CDROWN', value=row0+nrows-1,
                                comment='last row in readout window'))

            finalCards = self.finishHeaderKeys(cmd, visit, extraCards=addCards)

            self.writeImageFile(im, filepath, visit, cards=finalCards,
                                comment=self.comment, cmd=cmd)
        else:
            im = None
            filepath = "/no/such/dir/nosuchfile.fits"
            #for c in self.headerCards:
            #    cmd.inform('text="header card: %s"' % (str(c)))

        if im is not None:
            try:
                # proceed with crude serial overscan check.
                overscan = basicQA.serialOverscanStats(im, readRows=(row0, row0+nrows))

                # generate keywords.
                cmd.inform(f"overscanLevels={','.join(map(str, overscan.level.round(3)))}")
                cmd.inform(f"overscanNoise={','.join(map(str, overscan.noise.round(3)))}")

                # ensure overscans level/noise are compliants.
                status = basicQA.ensureOverscansAreInRange(overscan, self.actor.actorConfig['amplifiers'])
                msg = f'visitQA={visit},{qstr(status)}'
                if status == 'OK':
                    cmd.inform(msg)
                else:
                    cmd.warn(msg)
            except Exception as e:
                cmd.warn(f'text="failed to run QA checks: {e}"')

        filepath = pathlib.Path(filepath)
        filename = filepath.name

        # This is hideous. Need a proper splitter. Will be acceptable
        # when we dror filepath and thus the rootDir.
        rootDir = filepath.parents[2]
        dateDir = filepath.parent.parent.name

        self._setExposureState('idle', cmd=cmd)
        cmd.inform('filepath=%s,%s,%s' % (qstr(rootDir),
                                          qstr(dateDir),
                                          qstr(filename)))


        ids = self.actor.ids.idDict
        cmd.inform('spsFileIds=%s,%s,%d,%d,%d' % (ids['camName'],
                                                  qstr(dateDir),
                                                  visit,
                                                  ids['spectrograph'],
                                                  self.armNum(cmd)))

        return im, filepath

    def fixupImage(self, im, cmd):
        """Apply any post-readout corrections to images.

        Current used for:
         - INSTRM-1100: swap b2 amps: 0_1 (idx=1) <-> 1_2 (idx=6)

        Args
        ----
        im : `ndarray`
          raw image to process, as just read out. May be modified in place.
        cmd : `actorcore.Command`
          Command we can send commentary to.

        Returns
        -------
        im : `ndarray`
          raw image to write out.
        """

        if self.actor.ids.camName == 'b2':
            self.logger.info('swapping b2 amps')
            cmd.debug('text="fixup: swapping b2 amps"')

            ampWidth = im.shape[1] // 8
            amp_0_1 = im[:, 1*ampWidth:2*ampWidth].copy()
            im[:, 1*ampWidth:2*ampWidth] = im[:, 6*ampWidth:7*ampWidth]
            im[:, 6*ampWidth:7*ampWidth] = amp_0_1

        return im

    def writeImageFile(self, im, filepath, visit, 
                       cards=None, comment=None, cmd=None):
        """ Actually write the FITS file. 

        Args
        ----
        im : `numpy.ndarray`
          The image.
        filepath : `str` or `pathlib.Path`
          The full pathname of the file to write.
        visit : `int`
          The PFS visit number
        addCards : sequence of fitsio card dicts
          FITS cards to add.
        comment : `str`
          A comment to put at the start of the headeer.
        cmd : `actorcore.Command`
          Where to dribble info

        Returns
        -------
        filepath : `str`
          the input filepath

        The file is saved with RICE compression.

        """
        self.logger.info('creating fits file: %s', filepath)
        cmd.debug('text="creating fits file %s' % (filepath))

        finalCards = []
        if comment is not None:
            finalCards.append(dict(name='comment', value=comment))

        if cards is not None:
            finalCards.extend(cards)

        try:
            hdr = fitsio.FITSHDR(finalCards)
            fitsFile = fitsio.FITS(str(filepath), 'rw')
            fitsFile.write(None, header=hdr)
            fitsFile[-1].write_checksum()
            imHdr = fitsio.FITSHDR(self.header.getImageCards(cmd))
            fitsFile.write(im, extname="image", header=imHdr, compress='RICE')
            fitsFile[-1].write_checksum()
            fitsFile.close()
        except Exception as e:
            cmd.warn('text="failed to write fits file %s: %s"' % (filepath, e))
            self.logger.warn('failed to write fits file %s: %s', filepath, e)
            self.logger.warn('hdr : %s', hdr)

        return filepath

    def _grabInternalCards(self):
        cards = []

        return cards

    def _grabFirstFeeCards(self, cmd, fast=False):
        cards = []

        if fast:
            return cards
        try:
            fee = self.actor.fee
            ccdKeys = self.actor.ccdModel.keyVarDict

            fee.getCommandStatus('voltage')
            fee.getCommandStatus('bias')

        except Exception as e:
            cmd.warn(f'text="could not fetch new FEE cards: {e}"')
            return cards

        try:
            voltages = ('3V3M','3V3', '5VP','5VN','5VPpa', '5VNpa',
                        '12VP', '12VN', '24VN', '54VP')
            ccdKeys['feeVoltages'].set([fee.status[f'voltage.{v}'] for v in voltages])
        except Exception as e:
            cmd.warn(f'text="could not update FEE cards: {e}"')
            return cards

        return cards

    def _grabLastFeeCards(self, cmd):
        cards = []
        try:
            cards = fitsMhs.gatherHeaderCards(cmd, self.actor,
                                              modelNames=[self.actor.ccdModelName],
                                              shortNames=True)
        except Exception as e:
            cmd.warn(f'text="could not gather ccdModel cards: {e}"')
            return cards

        return cards

    def startHeader(self, cmd):
        """ Start the header. Called right after wipe is finished and integration started. Must not block! """

        if cmd is None:
            cmd = self.cmd

        self.header = spsFits.SpsFits(self.actor, cmd, self.imtype)
        self.headerCards = []
        self.headerCards.extend(self._grabFirstFeeCards(cmd))

    def getFinalTimecards(self, cmd):
        darkTime = np.round(float(max(self.expTime, self.darkTime)), 3)
        timecards = []
        timecards.append(dict(name='EXPTIME', value=np.round(float(self.expTime), 3),
                             comment='[s] Time detector was exposed to light'))
        timecards.append(dict(name='DARKTIME', value=darkTime,
                             comment='[s] Time between wipe and readout'))
        timecards.extend(self.timecards.getCards())

        return timecards

    def finishHeaderKeys(self, cmd, visit, extraCards=None):
        timecards = self.getFinalTimecards(cmd)

        allCards = self.header.finishHeaderKeys(cmd, visit, timeCards=timecards, 
                                                extraCards=extraCards,
                                                exptype=self.imtype, gain=1.3)
        allCards.extend(self._grabLastFeeCards(cmd))
        return allCards
