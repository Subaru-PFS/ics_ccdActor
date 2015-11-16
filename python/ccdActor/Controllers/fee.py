#!/usr/bin/env python

import argparse
import inspect
import logging
import serial
import sys
import time

from collections import OrderedDict

import astropy.io.fits as fits

class ModePreset(object):
    def __init__(self, name):
        self.name = name
        self.presets = None

    def __str__(self):
        return ("ModePreset(name=%s, %s)" %
                (self.name,
                 None if self.presets is None else ', '.join(["%s=%s" % (k,v)
                                                              for k,v in self.presets.iteritems()])))

    def define(self, preload=None, force=False, 
               P_off =None, P_on =None,
               S_off =None, S_on =None,
               DG_off=None, DG_on=None,
               SW_off=None, SW_on=None,
               RG_off=None, RG_on=None,
               OG=None,
               RD=None,
               OD=None,
               BB=None):

        if self.presets is not None and not force:
            raise RuntimeError("Mode preset values can only be defined once.")

        argValues = inspect.getargvalues(inspect.currentframe())

        if preload is not None:
            self.presets = preload.presets.copy()
        elif self.presets is None:
            self.presets = OrderedDict()

        for k in argValues.args:
            if k in ('self', 'force', 'preload'):
                continue
            v = argValues.locals[k]
            if v is not None:
                self.presets[k] = v
            else:
                if preload is None:
                    raise RuntimeError("All voltages must be defined for non-preloaded modes")

    def saveToFee(self, fee, channels=(0,1)):
        oldTimeout = fee.device.timeout
        fee.device.setTimeout(5.0)
        if False and self.preload:
            fee.sendCommandStr('lp,%s' % (self.name))
        for ch in channels:
            for k, v in self.presets.iteritems():
                if v is not None:
                    fee.doSet('bias', k, v, ch)
        fee.sendCommandStr('sp,%s' % (self.name))
        fee.device.setTimeout(oldTimeout)

class FeeSet(object):
    channels = []

    def __init__(self, name, letter, subs=(), 
                 setLetter='s', readLetter='r', getLetter='g',
                 converter=None, hasAll=False):
        self.name = name
        self.letter = letter
        self.subs = subs
        self.setLetter = setLetter
        self.readLetter = readLetter
        self.getLetter = getLetter
        self.converter = converter if converter is not None else str
        self.hasAll = hasAll
        
    def _getCmdString(self, cmdLetter, *parts):
        allParts = ["%s%s" % (cmdLetter, self.letter)]
        allParts.extend(parts)
        return ','.join(allParts)

    def setVal(self, subName, value):
        """ Return the command string for a 'set' function. """

        if not self.setLetter:
            raise RuntimeError("Cannot set %s(%s)!" % (self.name, subName))
        if subName not in self.subs:
            raise RuntimeError("Cannot set unknown %s (%s). Valid=%s" % (self.name, subName,
                                                                         self.subs))
        if value:
            return self._getCmdString(self.setLetter, subName, str(value))
        else:
            return self._getCmdString(self.setLetter, subName)

    def _getVal(self, subName, letter):
        """ Return the command string for a 'get' function. """

        if not letter:
            raise RuntimeError("Cannot get %s(%s)!" % (self.name, subName))

        if subName:
            if subName is 'all' and self.hasAll:
                return self._getCmdString(letter, subName)
            if subName not in self.subs:
                raise RuntimeError("Cannot get unknown %s (%s) hasAll=%s. Valid=%s" % (self.name, subName,
                                                                                       self.hasAll,
                                                                                       self.subs))
            return self._getCmdString(letter, subName)
        else:
            return self._getCmdString(letter)

    def getVal(self, subName):
        """ Return the command string for a 'get' function. """

        return self._getVal(subName, self.getLetter)

    def readVal(self, subName):
        """ Return the command string for a 'read' function. """

        return self._getVal(subName, self.readLetter)

    def _ampName(self, ampNum, leg='n'):
        """ Return the FEE controller's name for an amp (just for the so command). 

        Parameters
        ----------
        ampNum - int
           The 0..namps-1 index of an amp.
        leg -- ('n','p')
           Negative or Positive leg. 
        """

        ampNum = int(ampNum)
        return "%d%s,ch%d" % (ampNum%4, leg, ampNum/4)

class FeeChannelSet(FeeSet):
    channels = [0,1]

    def setVal(self, subName, channel, value):
        """ Return the command string for a 'set' function. """

        if not self.setLetter:
            raise RuntimeError("Cannot set %s(%s)!" % (self.name, subName))
        if subName not in self.subs:
            raise RuntimeError("Cannot set unknown %s (%s). Valid=%s" % (self.name, subName,
                                                                         self.subs))
        if channel not in (0,1):
            raise RuntimeError("Channel must be 0 or 1 (%s) for %s(%s)!" % (channel, self.name, subName))
            
        return self._getCmdString(self.setLetter, subName, 'ch%d' % (channel), str(value))

    def _getVal(self, subName, channel, letter):
        """ Return the command string for a 'get' function. """

        if not letter:
            raise RuntimeError("Cannot get %s(%s)!" % (self.name, subName))

        if channel not in (0,1):
            raise RuntimeError("Channel must be 0 or 1 (%s) for %s(%s)!" % (channel, self.name, subName))
            
        if subName is 'all' and self.hasAll:
            return self._getCmdString(letter, subName, 'ch%d' % (channel))
        if subName not in self.subs:
            raise RuntimeError("Cannot get unknown %s (%s) hasAll=%s. Valid=%s" % (self.name, subName,
                                                                                   self.hasAll,
                                                                                   self.subs))
        return self._getCmdString(letter, subName, 'ch%d' % (channel))

    def getVal(self, subName, channel):
        """ Return the command string for a 'get' function. """

        return self._getVal(subName, channel, self.getLetter)

    def readVal(self, subName, channel):
        """ Return the command string for a 'read' function. """

        return self._getVal(subName, channel, self.readLetter)

class fee(object):
    def __init__(self, actor, name,
                 logLevel=logging.DEBUG, sendImage=None,
                 noConnect=False, noPowerup=False):
        
        port = '/dev/ttyS1'
        self.logger = logging.getLogger()
        self.logger.setLevel(logLevel)
        self.device = None
        self.status = OrderedDict()
        self.devConfig = dict(port=port, 
                              baudrate=38400,
                              timeout=2.0)  # The RTD routines need > 0.5s.
        self.devConfig['writeTimeout'] = 10 * 1.0/(self.devConfig['baudrate']/8.0)
        self.EOL = '\n'
        self.ignoredEOL = '\r'

        self.lockConfig()
        self.defineCommands()

        self.activeMode = None
        self.defineModes()

        if noConnect is True:
            return
        self.setDevice(port)
        
        if sendImage is not None:
            self.sendImage(sendImage)
        else:
            if not noPowerup:
                self.powerUp()
            

    def stop(self):
        pass
    def start(self):
        pass
    
    def setDevice(self, devName):
        """ """
        self.devName = devName
        self.connectToDevice()

    def connectToDevice(self):
        """ Establish a new connection to the FEE. Any old connection is closed.  """

        if self.device:
            self.device.close()
            self.device = None

        if self.devName:
            self.device = serial.Serial(**self.devConfig)
    
    def powerUp(self, preset='erase'):
        """ Bring the FEE up to a sane and useable configuration. 

        Specifically, and in order: 
          1. power supplies on
          2. mode voltage set (default=erase)
          3. clocks enabled, but idle.
        """

        print self.sendCommandStr('se,all,on')
        print self.sendCommandStr('lp,%s' % (preset))
        print self.sendCommandStr('se,Clks,on')

        # Send a spurious read, to paper over a device error on the first read.
        self.sendCommandStr('ro,2p,ch1')

    def getCommandStatus(self, cset):
        status = OrderedDict()

        if cset.getLetter is None:
            return status

        if cset.channels:
            for chan in cset.channels:
                try:
                    all = self.doGetAll(cset.name, chan)
                    if len(all) != len(cset.subs):
                        raise IndexError("getAll returned %d items instead of the required %d" % (len(all),
                                                                                                  len(cset.subs)))
                    all = dict(zip(cset.subs, all))
                except Exception:
                    all = {}
                    for k in cset.subs:
                        all[k] = self.doGet(cset.name, k, chan)
                    
                for k in cset.subs:       
                    status["%s.ch%d.%s" % (cset.name, chan, k)] = all[k]
        else:
            try:
                all = self.doGetAll(cset.name)
                if len(all) != len(cset.subs):
                    raise IndexError("getAll returned %d items instead of the required %d" % (len(all),
                                                                                              len(cset.subs)))
                all = dict(zip(cset.subs, all))
            except Exception:
                all = {}
                for k in cset.subs:
                    all[k] = self.doGet(cset.name, k)
                    
            for k in cset.subs:       
                status["%s.%s" % (cset.name, k)] = all[k]

        return status

    def getAllStatus(self, skip=None):
        newStatus = OrderedDict()

        for csetName in self.commands.keys():
            if skip is not None and csetName in skip:
                continue
            cset = self.commands[csetName]
            cmdStatus = self.getCommandStatus(cset)
            newStatus.update(cmdStatus)

        self.status = newStatus
        return self.status

    def getTemps(self):
        temps = []
        for probe in 'FEE', 'PA', 'ccd0', 'ccd1':
            val = self.sendCommandStr('rt,%s' % (probe))
            temps.append(float(val))

        return temps
                         
    def powerDown(self):
        """ Bring the FEE down to a sane and stable idle. """

        print self.sendCommandStr('se,Clks,off')
        print self.sendCommandStr('se,all,off')

    def printStatus(self):
        for k, v in self.status.iteritems():
            print k, ': ', v

    def statusAsCards(self, useCache=False):
        if useCache is False:
            self.getAllStatus()
        cards = []
        for k,v in self.status.iteritems():
            c = fits.Card('HIERARCH %s' % (k), v)
            cards.append(c)
        for probe in 'FEE', 'PA', 'ccd0', 'ccd1':
            val = self.sendCommandStr('rt,%s' % (probe))
            c = fits.Card('HIERARCH temp.%s' % (probe), val)
            cards.append(c)
                    
        return cards

    def lockConfig(self):
        self.logger.warn('locking firmware configuration')
        self.lockedConfig = True

    def unlockConfig(self):
        self.logger.warn('unlocking firmware configuration')
        self.lockedConfig = False

    def setSerial(self, serialType, serial):
        if serialType not in ('ADC', 'PA0'):
            raise RuntimeError("unknown serial number type: %s" % (serialType))

        if self.lockedConfig:
            raise RuntimeError("FEE configuration is locked!")
            
        print self.sendCommandStr('ss,%s,%s' % (serialType, serial))
        
    def _defineFullCommand(self, cmdSet):
        """ For a passed commandset, create methods to set&get values."""

        self.commands[cmdSet.name] = cmdSet

    def defineModes(self):
        self.presets = OrderedDict()

        self.presets['erase'] = m = ModePreset('erase')
        m.define(OG=6.0, RD=-12.0, OD=-5.0, BB=0.2,
                 P_off = 6.0, P_on = 6.0,
                 S_off = 6.0, S_on = 6.0,
                 DG_off= 6.0, DG_on= 6.0,
                 SW_off= 6.0, SW_on= 6.0,
                 RG_off= 6.0, RG_on= 6.0)

        self.presets['read'] = m = ModePreset('read')
        m.define(OG=-4.5, RD=-12.0, OD=-20.0, BB=30.0,
                 P_off = 3.0, P_on = -5.0,
                 S_off = 3.0, S_on = -6.0,
                 DG_off= 5.0, DG_on=  5.0,
                 SW_off= 5.0, SW_on= -6.0,
                 RG_off= 2.0, RG_on= -7.5)

        self.presets['expose'] = m = ModePreset('expose')
        m.define(preload=self.presets['read'], 
                 OG=-4.5, RD=-5.0, OD=-5.0, BB=45.0)

        self.presets['wipe'] = m = ModePreset('wipe')
        m.define(preload=self.presets['read'], 
                 OG=-4.5, RD=-12.0, OD=-20.0, BB=30.0)


    def saveModesOnFee(self, modes=None):
        """ Save our voltage presets to the FEE. """
        
        if isinstance(modes, basestring):
            modes = modes,
        if modes is None:
            modes = self.presets.keys()
        for m in modes:
            p = self.presets[m]
            p.saveToFee(self)

    def setVoltage(self, mode, name, value, doSet=False):
        """ Change a single voltage in a single mode. """

        if mode is not None:
            m = self.presets[mode]
            kws = dict(name=value, force=True)
            print "kws: %s" % (kws)
            m.define(**kws)

            if doSet:
                m.saveToFee(self)
        else:
            for ch in 0,1:
                old = self.doGet('bias', name, ch)
                self.doSet('bias', name, value, ch)
                new = self.doGet('bias', name, ch)
                self.logger.info("changed ch%d %s from %s to %s" % (ch, name, old, new))
            
        
    def defineCommands(self):
        self.commands = {}

        self.commands['revision'] = FeeSet('revision', 'r', ['FEE'], 
                                           setLetter=None)
        self.commands['serial'] = FeeSet('serial', 's', ['FEE', 'ADC', 'PA0'])

        """
        #define setPowerEn   "se" // must include 0 or 1 for off or on 
        #define getPowerEn   "ge" 
        #define pe_3V3reg   "3V3" 
        #define pe_5Vreg    "5V" 
        #define pe_12Vreg   "12V" 
        #define pe_24Vreg   "24V" 
        #define pe_54Vreg   "54V" 
        #define pe_Preamp   "PA" 
        #define pe_LVDS     "LVDS" 
        #define pe_Vbb0     "Vbb0"// Bias amplifier enable 
        #define pe_Vbb1     "Vbb1"// Bias amplifier enable 
        #define pe_all      "all" 
        #define pe_on     "on" 
        #define pe_off    "off" 
        """
        self.commands['enable'] = FeeSet('enable', 'e', ['all', 
                                                         '3V3','5V','12V','24V','54V',
                                                         'PA','LVDS',
                                                         'Vbb0', 'Vbb1'], 
                                         getLetter=None,)
        """
        //Read/calibrate supply voltages
        #define calSupplyVoltage "cv"   //calibrate voltage channel
        #define getSupplyVoltage "gv"   //read voltage
        #define gv_3V3Micro "3V3M"
        #define gv_3V3Other "3V3"
        #define gv_5Vpos "5VP"
        #define gv_5Vneg "5VN"
        #define gv_5Vpos_pa "5VPpa"
        #define gv_5Vneg_pa "5VNpa"
        #define gv_12Vpos "12VP"
        #define gv_12Vneg "12VN"
        #define gv_24Vneg "24VN"
        #define gv_54Vpos "54VP"
        """
        self.commands['voltage'] = FeeSet('voltage', 'v', 
                                          ['3V3M','3V3',
                                           '5VP','5VN','5VPpa', '5VNpa',
                                           '12VP', '12VN', '24VN', '54VP'],
                                          converter=float,
                                          setLetter='c', getLetter='r', hasAll=True)
        """
        // Set/Get the CDS offset voltages 
        #define setCDS_OS "so"
        #define getCDS_OS "go"
        #define getCDS_OS "ro"
        # define co_0pos "0p" 
        # define co_0neg "0n" 
        # define co_1pos "1p" 
        # define co_1neg "1n" 
        # define co_2pos "2p" 
        # define co_2neg "2n" 
        # define co_3pos "3p" 
        # define co_3neg "3n"
        #  define co_0 "ch0" 
        #  define co_1 "ch1"
        """
        self.commands['offset'] = FeeChannelSet('offset', 'o', 
                                                ['0p','0n','1p','1n',
                                                 '2p','2n','3p','3n'],
                                                converter=float,
                                                getLetter='r', hasAll=True)
        """
        // Set/get the clock Bias Voltages
        #define setClockBias "sb" // COMMAND
        #define getClockBias "gb" 
        #define rdClockBias  "rb" // reads the actual voltage 
        #define cb_Ppos      "P_on" // PARAMETER 1
        #define cb_Pneg      "P_off"
        #define cb_DGpos     "DG_on"
        #define cb_DGneg     "DG_off"
        #define cb_Spos      "S_on"
        #define cb_Sneg      "S_off"
        #define cb_SWpos     "SW_on" // Summing Well
        #define cb_SWneg     "SW_off"
        #define cb_RGpos     "RG_on" // Reset Gate
        #define cb_RGneg     "RG_off"
        #define cb_OG        "OG"
        #define cb_RD        "RD"
        #define cb_OD        "OD"
        #define cb_BB        "BB"
        #   define cb_0         "ch0" // PARAMETER 2
        #   define cb_1         "ch1"
        """
        self.commands['bias'] = FeeChannelSet('bias', 'b', 
                                              ['P_on','P_off',
                                               'DG_on', 'DG_off',
                                               'S_on', 'S_off',
                                               'SW_on', 'SW_off',
                                               'RG_on', 'RG_off',
                                               'OG', 'RD', 'OD', 'BB'],
                                              converter=float,
                                              getLetter='r', hasAll=True)

        """
        //load/save bias presets

        #define loadDACPresets "lp"
        #define saveDACPresets "sp"
        #define pb_erase       "erase"
        #define pb_read        "read"
        #define pb_expose      "expose"
        #define pb_wipe        "wipe"
        #define pb_biasTest1   "BT1"
        #define pb_offset      "offset"
        #define pb_osTest1     "0T1"
        """
        self.commands['preset'] = FeeSet('preset', 'p', 
                                         ["erase", "read", "expose", "wipe", "offset", 
                                          "BT1"],
                                         getLetter=None,
                                         setLetter='l')

    def allKeys(self, setName):
        try:
            cmdSet = self.commands[setName]
        except AttributeError as e:
            raise e

        return cmdSet.subs

    def doSet(self, setName, subName, value, channel=None):
        try:
            cmdSet = self.commands[setName]
        except AttributeError as e:
            raise e

        if channel is not None:
            cmdStr = cmdSet.setVal(subName, channel, value)
        else:
            cmdStr = cmdSet.setVal(subName, value)

        return self.sendCommandStr(cmdStr)

    def doGet(self, setName, subName=None, channel=None):
        try:
            cmdSet = self.commands[setName]
        except AttributeError as e:
            raise e

        if channel is not None:
            cmdStr = cmdSet.getVal(subName, channel)
        else:
            cmdStr = cmdSet.getVal(subName)

        return cmdSet.converter(self.sendCommandStr(cmdStr))

    def doGetAll(self, setName, channel=None):
        try:
            cmdSet = self.commands[setName]
        except AttributeError as e:
            raise e

        if not cmdSet.hasAll:
            raise AttributeError("%s has no fetch-all command.")
        
        if channel is not None:
            cmdStr = cmdSet.getVal('all', channel)
        else:
            cmdStr = cmdSet.getVal('all')
        ret = self.sendCommandStr(cmdStr)

        vals = [cmdSet.converter(v) for v in ret.split(',')]
        return vals
        
    def raw(self, cmdStr):
        return self.sendCommandStr(cmdStr)

    def sendImage(self, path, verbose=True, doWait=True):
        """ Download an image file. """

        eol = chr(0x0a)
        ack = chr(0x06)
        nak = chr(0x15)
        lineNumber = 1
        maxRetries = 5

        if doWait:
            self.device.timeout = 15
            ret = self.device.readline()
            retline = ret.strip()
            isBootLoader = 'Bootloader' in retline
            if not isBootLoader:
                raise RuntimeError("not at bootloader prompt (%s)" % (retline))
            isBlank = retline[-1] == 'B'
            self.logger.warn('at bootloader: %s (blank=%s), from %r' % (isBootLoader, isBlank, ret))
            if not isBlank:
                self.device.write('*')
        else:
            self.device.write('*')

        ret = self.device.readline()
        ret = ret.strip()
        if not ret.startswith('*Waiting for Data...'):
            self.logger.warn('at bootloader *, got %r' % (ret))
            ret = self.device.readline()

        logLevel = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.device.timeout = self.devConfig['timeout']
        with open(path, 'rU') as hexfile:
            lines = hexfile.readlines()
            t0 = time.time()
            self.logger.info('sending image file %s, %d lines' % (path, len(lines)))
            for l in lines:
                l = l.strip()
                if l[0] == ';':
                    continue
                retries = 0
                while True:
                    if verbose and retries > 0:
                        self.logger.warn('resending line %d; try %d' % (lineNumber, 
                                                                        retries))
                    fullLine = l+eol
                    if verbose and lineNumber%100 == 1:
                        self.logger.info('sending line %d / %d', lineNumber, len(lines))
                    self.logger.debug("sending command :%r:", fullLine)
                    self.device.write(fullLine)
                    retline = self.device.read(size=len(l)+len(eol)+1)
                    retline = retline.translate(None, '\x11\x13')

                    if l != retline[:len(l)]:
                        self.logger.warn("command echo mismatch. sent :%r: rcvd :%r:" % (l, retline))
                    ret = retline[-1]
                    lineNumber += 1
                    if ret == ack or l == ':00000001FF':
                        break
                    if ret != nak:
                        raise RuntimeError("unexpected response (%r in %r) after sending line %d" %
                                           (ret, retline, lineNumber-1))
                    retries += 1
                    if retries >= maxRetries:
                        raise RuntimeError("too many retries (%d) on line %d" %
                                           (retries, lineNumber-1))

            t1 = time.time()
            self.logger.info('sent image file %s in %0.2f seconds' % (path, t1-t0))

        self.logger.setLevel(logLevel)

    def sendCommandStr(self, cmdStr, noTilde=False, EOL=None):
        if EOL is None:
            EOL = self.EOL
        if noTilde:
            fullCmd = "%s%s" % (cmdStr, EOL)
        else:
            fullCmd = "~%s%s" % (cmdStr, EOL)

        self.logger.debug("sending command :%r:" % (fullCmd))
        try:
            self.device.write(fullCmd)
        except serial.writeTimeoutError as e:
            raise
        except serial.SerialException as e:
            raise
        except Exception as e:
            raise

  
        ret = self.readResponse()
        if ret != fullCmd.strip():
            raise RuntimeError("command echo mismatch. sent :%r: rcvd :%r:" % (cmdStr, ret))
 
        return self.readResponse()

    def readResponse(self, EOL=None):
        """ Read a single response line, up to the next self.EOL.

        Returns
        -------
        response
           A string, with trailing EOL removed.

        Notes
        -----
        Ignores CRs
        """

        if EOL is None:
            EOL = self.EOL

        response = ""

        while True:
            try:
                c = self.device.read(size=1)
                # self.logger.debug("received char :%r:" % (c))
            except serial.SerialException as e:
                raise
            except serial.portNotOpenError as e:
                raise
            except Exception as e:
                raise

            if c == '':
                self.logger.warn('pyserial device read(1) timed out')

            if self.ignoredEOL is not None and c == self.ignoredEOL:
                self.logger.debug("ignoring %r" % (c))
                continue
            if c in (EOL, ''):
                break
            response += c
                
        self.logger.debug("received :%s:" % (response))
        return response

    def setRaw(self, cmdStr):
        """ Send a raw commmand string. Well we add the ~ and EOL. """
        
        return self.sendCommandStr(cmdStr)

    def getRaw(self, cmdStr):
        """ Send a raw commmand string. Well we add the ~ and EOL. """
        
        return self.sendCommandStr(cmdStr)

    def _ampName(self, ampNum, leg='n'):
        ampNum = int(ampNum)
        channel = ampNum/4
        return "%d%s,ch%d" % (ampNum%4, leg, channel)

    def ampParts(self, ampNum, leg='n'):
        ampNum = int(ampNum)
        channel = ampNum/4
        return "%d%s" % (ampNum%4, leg), channel

    def setMode(self, newMode):
        self.sendCommandStr('lp,%s' % (newMode))

    def setOffsets(self, amps, levels, leg='n', pause=0.0):
        if len(amps) != len(levels):
            raise RuntimeError("require same number of amps (%r) and levels (%r)" % (amps, levels))
        for i, a in enumerate(amps):
            ampName, channel = self.ampParts(a, leg=leg)
            ret = self.doSet('offset', ampName, round(levels[i],2), channel=channel)
            if ret != 'SUCCESS':
                self.logger.info("raw received :%r:" % (ret))
            else:
                self.logger.debug("raw received :%r:" % (ret))
            if not ret.endswith('SUCCESS'):
                raise RuntimeError('setLevels command returned: %s' % (ret))
            if pause > 0:
                time.sleep(pause)

    def zeroOffsets(self, amps=None, leg=True):
        if amps is None:
            amps = range(8)
        levels = [0.0] * len(amps)

        if leg is True:
            legs = ('n','p')
        else:
            legs = leg,
    
        if 'p' in legs:
            self.setOffsets(amps, levels, leg='p')
        if 'n' in legs:
            self.setOffsets(amps, levels, leg='n')

    def setPreset(self, name):
        vset = self.presets[name]
        for ch in 0, 1:
            for k, v in vset.iteritems():
                self.doSet('bias', k, v, ch)

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if isinstance(argv, basestring):
        argv = argv.split()

    parser = argparse.ArgumentParser(description="Send one or more commands to the FEE controller.",
                                     epilog="At least one command must be specified.\n")

    parser.add_argument('-p', '--port', 
                        type=str, default='/dev/ttyS1',
                        help='the port to use. Currently must be a tty name. Default=%(default)s')
    parser.add_argument('-r', '--raw', action='append',
                        help='a raw command to send. The "~" is automatically prepended.')
    parser.add_argument('--debug', action='store_true',
                        help='show all traffic to the port.')

    args = parser.parse_args(argv)

    logLevel = logging.DEBUG if args.debug else logging.WARN

    feeDev = fee(None, 'fee', logLevel=logLevel)
    if args.raw:
        for rawCmd in args.raw:
            print feeDev.getRaw(rawCmd)
    else:
        feeDev.getAllStatus()
        feeDev.printStatus()
    
if __name__ == "__main__":
    main()

