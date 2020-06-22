from importlib import reload

import logging
import os
import pathlib
import time
import threading

import numpy as np

import fitsio
from actorcore.utility import fits as fitsUtils
from actorcore.utility import timecards
from opscore.utility.qstr import qstr
import fpga.ccdFuncs as ccdFuncs
reload(fitsUtils)

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
        
        self.pleaseStop = False
        
    def __str__(self):
        return "Exposure(imtype=%s, expTime=%s, startedAt=%s)" % (self.imtype,
                                                                  self.expTime,
                                                                  self.startTime)
    def _setExposureState(self, newState, cmd=None):
        if cmd is None:
            cmd = self.cmd
        if newState == 'aborted':
            cmd.warn('exposureState=%s' % (newState))
        else:
            cmd.inform('exposureState=%s' % (newState))
        self.exposureState = newState
        
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
        self._setExposureState('aborted')
        self.cmd.fail('exposureState="aborted"')
    
    def finish(self):
        if self.exposureState != 'idle':
            self.cmd.warn('text="stopping a non-idle exposure: %s"' % (str(self)))
            
        self._setExposureState('idle')
        
    def wipe(self, cmd=None, nrows=None):
        """ Wipe/flush the detector and put it in integration mode. """

        self._setExposureState('wiping', cmd=cmd)
        ccdFuncs.wipe(self.ccd, feeControl=self.fee, nrows=nrows)
        self.timecards = timecards.TimeCards()
        self._setExposureState('integrating', cmd=cmd)
        self.startTime = time.time()
        self.grabStartingHeaderKeys(cmd)

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

    def readout(self, imtype=None, expTime=None, darkTime=None,
                visit=None, obstime=None, comment='',
                doFeeCards=True, doModes=True,
                nrows=None, ncols=None, cmd=None, doRun=True):
        if imtype is not None:
            self.imtype = imtype
        if expTime is not None:
            self.expTime = expTime
        if comment is not None:
            self.comment = comment

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
        if self.headerCards is None:
            self.grabStartingHeaderKeys(cmd)
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
                darkTime = self.expTime + 2*0.38
        self.darkTime = darkTime
        
        if doRun:
            self.timecards.end(expTime=self.expTime)
            self.finishHeaderKeys(cmd, visit)
            im, _ = ccdFuncs.readout(self.imtype, expTime=self.expTime,
                                     darkTime=self.darkTime,
                                     ccd=self.ccd, feeControl=self.fee,
                                     nrows=nrows, ncols=ncols,
                                     doFeeCards=False, doModes=doModes,
                                     comment=self.comment,
                                     doSave=False,
                                     rowStatsFunc=rowCB)

            filepath = self.makeFilePath(visit, cmd)
            self.writeImageFile(im, filepath, visit,
                                comment=self.comment, cmd=cmd)
        else:
            im = None
            filepath = "/no/such/dir/nosuchfile.fits"
            for c in self.headerCards:
                cmd.inform('text="header card: %s"' % (str(c)))

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

    def getImageCards(self, cmd=None):
        """Return the FITS cards for the image HDU, WCS, basically.

        We do not et have a WCS, so only return the required Subaru cards.
        """

        allCards = []
        allCards.append(dict(name='INHERIT', value=True, comment='Recommend using PHDU cards'))
        allCards.append(dict(name='BIN-FCT1', value=1, comment='X-axis binning'))
        allCards.append(dict(name='BIN-FCT2', value=1, comment='Y-axis binning'))
        return allCards

    def writeImageFile(self, im, filepath, visit, addCards=None, comment=None, cmd=None):
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
        
        cards = []
        if comment is not None:
            cards.append(dict(name='comment', value=comment))

        if addCards is not None:
            cards.extend(addCards)
        cards.extend(self.headerCards)

        try:
            hdr = fitsio.FITSHDR(cards)
            fitsFile = fitsio.FITS(str(filepath), 'rw')
            fitsFile.write(None, header=hdr)
            fitsFile[-1].write_checksum()
            imHdr = fitsio.FITSHDR(self.getImageCards(cmd))
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

    def _getInstHeader(self, cmd):
        """ Gather FITS cards from all actors we are interested in. """

        cmd.debug('text="fetching MHS cards..."')
        modelNames = list(self.actor.models.keys())
        modelNames.remove(self.actor.ccdModelName)
        cards = fitsUtils.gatherHeaderCards(cmd, self.actor,
                                            modelNames=modelNames,shortNames=True)
        cmd.debug('text="fetched %d MHS cards..."' % (len(cards)))

        return cards

    def _grabFirstFeeCards(self, cmd):
        cards = []
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
            fee = self.actor.fee
            ccdKeys = self.actor.ccdModel.keyVarDict

            #fee.getCommandStatus('voltage')
            #status = fee.getCommandStatus('bias')

        except Exception as e:
            cmd.warn(f'text="could not fetch FEE cards: {e}"')
            return cards

        try:
            voltages = ('3V3M','3V3', '5VP','5VN','5VPpa', '5VNpa',
                        '12VP', '12VN', '24VN', '54VP')
            #ccdKeys.feeVoltages.set([status[f'bias.{v}'] for v in voltages])
        except Exception as e:
            cmd.warn(f'text="could not update FEE cards: {e}"')
            return cards

        try:
            cards = fitsUtils.gatherHeaderCards(cmd, self.actor,
                                                modelNames=[self.actor.ccdModelName],
                                                shortNames=True)
        except Exception as e:
            cmd.warn(f'text="could not gather ccdModel cards: {e}"')
            return cards

        return cards

    def grabStartingHeaderKeys(self, cmd):
        """ Start the header. Called right after wipe is finished and integration started. Must not block! """

        if cmd is None:
            cmd = self.cmd

        self.headerCards = []
        self.headerCards.extend(self._getInstHeader(cmd))
        self.headerCards.extend(self._grabFirstFeeCards(cmd))

    def finishHeaderKeys(self, cmd, visit):
        """ Finish the header. Called just before readout starts. Must not block! """

        if cmd is None:
            cmd = self.cmd

        timecards = self.timecards.getCards()

        gain = 1.3
        detectorId = self.actor.ids.camName
        try:
            xcuModel = self.actor.xcuModel
            detectorTemp = xcuModel.keyVarDict['visTemps'].getValue()[-1]
        except Exception as e:
            cmd.warn(f'text="failed to get detector temp for Subaru: {e}"')
            detectorTemp = 9998.0

        imtype = self.imtype.upper()
        if imtype == 'ARC':
            imtype = 'COMPARISON'
        allCards = []
        allCards.append(dict(name='DATA-TYP', value=imtype, comment='Subaru-style exposure type'))
        allCards.append(dict(name='FRAMEID', value=f'PFSA{visit:06d}00', comment='Sequence number in archive'))
        allCards.append(dict(name='EXP-ID', value=f'PFSE00{visit:06d}', comment='PFS exposure visit number'))
        allCards.append(dict(name='DETECTOR', value=detectorId, comment='Name of the detector/CCD'))
        allCards.append(dict(name='GAIN', value=gain, comment='[e-/ADU] AD conversion factor'))
        allCards.append(dict(name='DET-TMP', value=detectorTemp, comment='[K] Detector temperature'))
        allCards.append(dict(name='DISPAXIS', value=2, comment='Dispersion axis (along columns)'))
        allCards.append(dict(name='COMMENT', value='################################ PFS main IDs'))
        allCards.append(dict(name='W_VISIT', value=visit, comment='PFS exposure visit number'))
        allCards.append(dict(name='W_ARM', value=self.armNum(cmd), comment='Spectrograph arm 1=b, 2=r, 3=n, 4=medRed'))
        allCards.append(dict(name='W_SPMOD', value=self.actor.ids.specNum, comment='Spectrograph module. 1-4 at Subaru'))
        allCards.append(dict(name='W_SITE', value=self.actor.ids.site, comment='PFS DAQ location: Subaru, Jhu, Lam, Asiaa'))

        allCards.append(dict(name='COMMENT', value='################################ Time cards'))
        allCards.append(dict(name='EXPTIME', value=np.round(float(self.expTime), 3),
                             comment='[s] Estimate of time detector was exposed to light'))
        allCards.append(dict(name='DARKTIME', value=np.round(float(self.darkTime), 3),
                             comment='[s] Estimate of time between wipe and readout'))
        
        allCards.extend(timecards)
        allCards.extend(self.headerCards)
        allCards.extend(self._grabLastFeeCards(cmd))

        self.headerCards = allCards
