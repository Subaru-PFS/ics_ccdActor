import logging
import os
import time
import threading

import numpy as np

import astropy.io.fits as pyfits

from actorcore.utility import fits as fitsUtils
from opscore.utility.qstr import qstr

import fpga.ccdFuncs as ccdFuncs

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
        self._setExposureState('integrating', cmd=cmd)
        self.grabHeaderKeys(cmd)

    def armNum(self, cmd):
        """Return the correct arm number: 1, 2, or 4. 

        For the red cryostats, we have two arm numbers: 2 for low res,
        and 4 for medium res. This number is used (only?) in the
        filename. Resolve which to use.

        We _want_ to use the dcbActor rexm keyword. But we also allow
        manually overriding that from the self.actor.grating
        variable. That may only ever be used for code testing.

        """
        
        if self.actor.ids.arm is not 'r':
            return self.actor.ids.armNum
        if self.actor.grating is not 'real':
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

        path = os.path.join('/data', 'pfs', time.strftime('%Y-%m-%d'))
        path = os.path.expandvars(os.path.expanduser(path))
        if not os.path.isdir(path):
            os.makedirs(path, 0o755)

        ids = self.actor.ids
        filename = 'PF%sA%06d%d%d.fits' % (ids.site, visit,
                                           ids.specNum, self.armNum(cmd))

        return os.path.join(path, filename)

    def readout(self, imtype=None, expTime=None, darkTime=None,
                visit=None, comment='',
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
            
        # If we are not told what our dark time is, guess that the exposure was not
        # paused.
        if darkTime is None:
            if self.expTime == 0:
                darkTime = 0.0
            else:
                darkTime = self.expTime + 2*0.38
        self.darkTime = darkTime
        
        if cmd is None:
            cmd = self.cmd
            
        def rowCB(line, image, errorMsg="OK", cmd=cmd, **kwargs):
            imageHeight = image.shape[0]
            everyNRows = 250
            if (line % everyNRows != 0) and (line < imageHeight-1):
                return
            cmd.inform('readRows=%d,%d' % (line, imageHeight))

        if self.exposureState != 'integrating':
            cmd.warn('text="reading out detector in odd state: %s"' % (str(self)))
        if not hasattr(self, 'headerCards'):
            self.grabHeaderKeys(cmd)
            
        self._setExposureState('reading', cmd=cmd)
        if doRun:
            im, _ = ccdFuncs.readout(self.imtype, expTime=self.expTime,
                                     darkTime=self.darkTime,
                                     ccd=self.ccd, feeControl=self.fee,
                                     nrows=nrows, ncols=ncols,
                                     doFeeCards=False, doModes=doModes,
                                     comment=self.comment,
                                     doSave=False,
                                     rowStatsFunc=rowCB)

            filepath = self.makeFilePath(visit, cmd)
            daqCards = ccdFuncs.fetchCards(self.imtype, self.fee,
                                           expTime=self.expTime, darkTime=self.darkTime)
            self.writeImageFile(im, filepath, visit, addCards=daqCards, cmd=cmd)
        else:
            im = None
            filepath = "/no/such/dir/nosuchfile.fits"
            for c in self.headerCards:
                cmd.inform('text="header card: %s"' % (str(c)))
                
        dirname, filename = os.path.split(filepath)
        rootDir, dateDir = os.path.split(dirname)

        self._setExposureState('idle', cmd=cmd)
        cmd.inform('filepath=%s,%s,%s' % (qstr(rootDir),
                                          qstr(dateDir),
                                          qstr(filename)))

        return im, filepath

    def addHeaderCards(self, hdr, cards, cmd):
        for card in cards:
            try:
                hdr.append(card)
            except Exception as e:
                cmd.warn('text="failed to add card %s to header: %s"' % (card, e))
                self.logger.warning("failed to add card to header: %s", e)
                self.logger.warning("failed card: %r", card)
    
    def writeImageFile(self, im, filepath, visit, addCards=None, comment=None, cmd=None):
        self.logger.warning('creating fits file: %s', filepath)
        cmd.debug('text="creating fits file %s' % (filepath))
        
        hdr = pyfits.Header()
        hdr.append(('W_VISIT', visit, 'PFS exposure visit number'))
        self.addHeaderCards(hdr, self.ccd.idCards(), cmd)
        self.addHeaderCards(hdr, self.ccd.geomCards(), cmd)
        if addCards is not None:
            self.addHeaderCards(hdr, addCards, cmd)
        if comment is not None:
            self.addHeaderCards(hdr, [comment], cmd)
        self.addHeaderCards(hdr, self.headerCards, cmd)
            
        try:
            pyfits.writeto(filepath, im, hdr, checksum=True)
        except Exception as e:
            cmd.warn('text="failed to write fits file %s: %s"' % (filepath, e))
            self.logger.warn('failed to write fits file %s: %s', filepath, e)
            self.logger.warn('hdr : %s', hdr)
        
        return filepath
        
    def _grabCcdCards(self):
        ccdName = 'ccd_%s' % (self.actor.ids.cam)
        cards = []
        cards.append(('COMMENT', '===================== CCD cards'),)

        try:
            keyDict = self.actor.models[ccdName].keyVarDict
        except Exception as e:
            self.cmd.warn('text="could not get %s cards: %s"' % (ccdName, e))
            cards.append(('COMMENT', 'FAILED TO GET CCD (%s) cards' % (ccdName)),)
            return cards
        
        return cards

    def _grabXcuCards(self):
        xcuName = 'xcu_%s' % (self.actor.ids.camName)
        cards = []
        cards.append(('COMMENT', '===================== XCU cards'),)

        try:
            keyDict = self.actor.models[xcuName].keyVarDict
        except Exception as e:
            self.cmd.warn('text="could not get %s cards: %s"' % (xcuName, e))
            cards.append(('COMMENT', 'FAILED TO GET XCU (%s) cards' % (xcuName)),)
            return cards

        motorCards = (('W_XCU_MOTOR%d_STATE', 'ccdMotor%d', 0, str, ''),
                      ('W_XCU_MOTOR%d_HOMESWITCH', 'ccdMotor%d', 1, bool, ''),
                      ('W_XCU_MOTOR%d_FARSWITCH', 'ccdMotor%d', 2, bool, ''),
                      ('W_XCU_MOTOR%d_STEPS', 'ccdMotor%d', 3, int, 'Full motor steps'),
                      ('W_XCU_MOTOR%d_MICRONS', 'ccdMotor%d', 4, float, 'um at FPA'))
                    
        for c in motorCards:
            cardName, keyName, idx, cnv, comment = c
            for motor in 1,2,3:
                c = fitsUtils.makeCardFromKey(self.cmd, keyDict,
                                              keyName % (motor), 
                                              cardName % (motor),
                                              idx=idx,
                                              cnv=cnv, comment=comment)
                cards.append(c)
            
        return cards

    def _grabDcbCards(self):
        cards = []
        cards.append(('COMMENT', '===================== DCB cards'),)

        try:
            keyDict = self.actor.models['dcb'].keyVarDict
        except:
            self.cmd.warn('text="could not get DCB cards"')
            cards.append(('COMMENT', 'FAILED TO GET DCB cards'),)
            return cards

        def ftL2cdm2(footLamberts):
            return np.round(float(footLamberts) * 3.426, 3)
        
        dcbCards = (('W_AIT_SRC_Ne',   'ne',    bool, 'AIT Ne lamp'),
                    ('W_AIT_SRC_Xe',   'xenon', bool, 'AIT Xe lamp'),
                    ('W_AIT_SRC_HgAr', 'hgar',  bool, 'AIT HgAr lamp'),
                    ('W_AIT_SRC_Qth',  'halogen',    bool, 'AIT halogen lamp'),
                    ('W_AIT_SRC_Atten',  'attenuator',    int, 'AIT int sphere attenuator value'),
                    ('W_AIT_SRC_diodeFlux',  'photodiode', ftL2cdm2, 'cd/m^2 at photodiode'),
                    )
                    
        for c in dcbCards:
            cardName, keyName, cnv, comment = c
            c = fitsUtils.makeCardFromKey(self.cmd, keyDict, keyName,
                                          cardName, cnv=cnv, comment=comment)
            cards.append(c)

        return cards

    def _grabEnuCards(self):
        enuName = "enu"         # Should be "enu_sm%d"
        cards = []
        cards.append(('COMMENT', '===================== ENU cards'),)

        try:
            keyDict = self.actor.models[enuName].keyVarDict
        except Exception as e:
            self.cmd.warn('text="could not get ENU (%s) cards: %s"' % (enuName, e))
            cards.append(('COMMENT', 'FAILED TO GET ENU cards'),)
            return cards

        # slit=IDLE,operation,0.00000,-0.00000,0.00000,0.00000,0.00000,-0.00000
        slitCards = (('W_FCA_STATE', 'slit', 0, str, ''),
                     ('W_FCA_FOCUS', 'slit', 2, float, ''),
                     ('W_FCA_SHIFT', 'slit', 3, float, ''),
                     ('W_FCA_DITHER', 'slit', 4, float, ''),
                     ('W_FCA_PITCH', 'slit', 5, float, ''),
                     ('W_FCA_ROLL', 'slit', 6, float, ''),
                     ('W_FCA_YAW', 'slit', 7, float, ''))

        for c in slitCards:
            cardName, keyName, idx, cnv, comment = c
            c = fitsUtils.makeCardFromKey(self.cmd, keyDict,
                                          keyName, 
                                          cardName,
                                          idx=idx,
                                          cnv=cnv, comment=comment)
            cards.append(c)
        
        return cards

    def _grabInternalCards(self):
        cards = []

        return cards

    def _getInstHeader(self, cmd):
        """ Gather FITS cards from all actors we are interested in. """

        cmd.debug('text="fetching MHS cards..."')
        cards = fitsUtils.gatherHeaderCards(cmd, self.actor, shortNames=True)
        cmd.debug('text="fetched %d MHS cards..."' % (len(cards)))

        # Until we convert to fitsio, convert cards to pyfits
        pycards = []
        for c in cards:
            if isinstance(c, str):
                pcard = 'COMMENT', c
            else:
                pcard = c['name'], c['value'], c.get('comment', '')
            pycards.append(pcard)
            cmd.debug('text=%s' % (qstr("fetched card: %s" % (str(pcard)))))

        return pycards
    
    def grabHeaderKeys(self, cmd):
        """ Must not block! """

        if cmd is None:
            cmd = self.cmd
            
        self.headerCards = []
        self.headerCards.extend(self._getInstHeader(cmd))
        self.headerCards.extend(self._grabInternalCards())
        # self.headerCards.extend(self._grabCcdCards())
        self.headerCards.extend(self._grabXcuCards())
        self.headerCards.extend(self._grabEnuCards())
        self.headerCards.extend(self._grabDcbCards())
