#!/usr/bin/env python

from collections import OrderedDict
from importlib import reload

import os.path
import time

import opscore.protocols.keys as keys
import opscore.protocols.types as types
from opscore.utility.qstr import qstr

class FeeCmd(object):

    def __init__(self, actor):
        # This lets us access the rest of the actor.
        self.actor = actor

        # Declare the commands we implement. When the actor is started
        # these are registered with the parser, which will call the
        # associated methods when matched. The callbacks will be
        # passed a single argument, the parsed and typed command.
        #
        self.vocab = [
            ('fee', '@raw', self.raw),
            ('fee', 'download <pathname>', self.download),
            ('fee', 'bootstrap <pathname>', self.bootstrap),
            ('fee', 'calibrate', self.calibrate),
            ('fee', 'status [@(serial)] [@(temps)] [@(bias)] [@(voltage)] [@(offset)] [@(preset)]', self.status),
            ('fee', 'test1', self.test1),
            ('fee', 'setOffsets <n> <p> [@(save)]', self.setOffsets),
            ('feeTimes', '@raw', self.times),
            ('fee', 'setSerials [<ADC>] [<PA0>] [<CCD0>] [<CCD1>]', self.setSerials),
            ('fee', '@(setMode) @(idle|wipe|erase|expose|read|offset)', self.setMode),
            ('fee', 'setVoltageCalibrations [<v3V3M>] [<v3V3>] [<v5VP>] [<v5VN>] [<v5VPpa>] [<v5VNpa>] [<v12VP>] [<v12VN>] [<v24VN>] [<v54VP>]',
             self.setVoltageCalibrations),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
                                        keys.Key("pathname", types.String(),
                                                 help='the pathname of a .hex firmware file'),
                                        keys.Key("n", types.Float()*8,
                                                 help='N offsets'),
                                        keys.Key("p", types.Float()*8,
                                                 help='P offsets'),
                                        keys.Key("cnt", types.Int(),
                                                 help='a count'),
                                        keys.Key("ADC", types.Int(),
                                                 help='the ADC serial number'),
                                        keys.Key("PA0", types.Int(),
                                                 help='the preamp serial number'),
                                        keys.Key("CCD0", types.String(),
                                                 help='the serial number for CCD 0'),
                                        keys.Key("CCD1", types.String(),
                                                 help='the serial number for CCD 1'),
                                        keys.Key("v3V3M", types.Float()),
                                        keys.Key("v3V3", types.Float()),
                                        keys.Key("v5VP", types.Float()),
                                        keys.Key("v5VN", types.Float()),
                                        keys.Key("v5VPpa", types.Float()),
                                        keys.Key("v5VNpa", types.Float()),
                                        keys.Key("v12VP", types.Float()),
                                        keys.Key("v12VN", types.Float()),
                                        keys.Key("v24VN", types.Float()),
                                        keys.Key("v54VP", types.Float()),
        )

    def raw(self, cmd):
        """ Send a raw FEE command. """

        cmdTxt = cmd.cmd.keywords['raw'].values[0]

        ret = self.actor.fee.sendCommandStr(cmdTxt, noTilde=(cmdTxt in {'reset'}))
        cmd.finish('text=%s' % (qstr('returned: %s' % (ret))))  

    def _status(self, cmd, keys):
        """ Actually generate the keywords for the passed in keys. """

        for k, v in list(keys.items()):
            k = k.replace('.', '_')
            try:
                float(v)
            except:
                v = qstr(v)
                
            cmd.inform('%s=%s' % (k,v))
        
    def status(self, cmd, doFinish=True):
        """ Fetch some status keys. All of them by default. """

        cmdKeys = cmd.cmd.keywords

        anyDone = False
        for feeSet in 'serial', 'temps', 'bias', 'voltage', 'offset', 'preset':
            if feeSet in cmdKeys:
                keys = self.actor.fee.getCommandStatus(feeSet)
                self._status(cmd, keys)
                anyDone = True

        if not anyDone:
            keys = self.actor.fee.getAllStatus()
            self._status(cmd, keys)

        if doFinish:
            cmd.finish()

    def setMode(self, cmd):
        cmdKeys = cmd.cmd.keywords

        allModes = {'erase', 'idle', 'wipe', 'expose', 'read', 'offset'}
        mode = None
        for m in allModes:
            if m in cmdKeys:
                mode = m
                break

        self.actor.fee.setMode(mode)
        cmd.finish()
        
    def setOffsets(self, cmd):
        cmdKeys = cmd.cmd.keywords

        nOffsets = cmdKeys['n'].values
        pOffsets = cmdKeys['p'].values
        doSave = 'save' in cmdKeys
        
        amps = list(range(8))
        
        self.actor.fee.setOffsets(amps, nOffsets, leg='n', doSave=doSave)
        self.actor.fee.setOffsets(amps, pOffsets, leg='p', doSave=doSave)

        cmd.finish()
        
    def test1(self, cmd):
        """ Test core parts of the FEE. """

        S = self.actor.fee.getCommandStatus('serial')
        self._status(cmd, S)
        R = self.actor.fee.getCommandStatus('revision')
        self._status(cmd, R)

        V = self.actor.fee.getCommandStatus('voltage')
        self._status(cmd, V)

        T = self.actor.fee.getCommandStatus('temps')
        self._status(cmd, T)
        
        cmd.finish()
        
    def times(self, cmd):
        """ Test core parts of the FEE. """

        cmdTxt = cmd.cmd.keywords['raw'].values[0]
        cnt = 10 # cmd.cmd.keywords['cnt'].values[0]

        t0 = time.time()
        for i in range(cnt):
            ret = self.actor.fee.getRaw(cmdTxt)
        t1 = time.time()

        cmd.finish('text="total=%0.2fs, per=%0.04fs"' % (t1-t0, old_div((t1-t0),cnt)))
        
    def calibrate(self, cmd):
        """ Calibrate FEE DACs and load mode voltages. """

        fee = self.actor.fee

        cmd.inform('text="calibrating fee.... takes 30s or so..."')
        fee.calibrate()
        cmd.inform('text="fee calibrated..."')

        self.status(cmd)

    def download(self, cmd):
        """ Download firmware. """

        fee = self.actor.fee
        path = cmd.cmd.keywords['pathname'].values[0]

        if not os.path.exists(path):
            cmd.fail('text="firmware file cannot be opened (%s)"' % (path))
            return
        if os.path.splitext(path)[1] != '.hex':
            cmd.fail('text="firmware file must be a .hex file (%s)"' % (path))
            return

        fee.sendImage(path, sendReset=False, doWait=False)
        keys = self.actor.fee.sendCommandStr('gr')
        self._status(cmd, keys)
        
        cmd.finish('')

    def bootstrap(self, cmd):
        """ Download firmware. """

        import xcu_fpga.fee.feeControl as feeControl
        reload(feeControl)
        
        path = cmd.cmd.keywords['pathname'].values[0]

        if not os.path.exists(path):
            cmd.fail('text="firmware file cannot be opened (%s)"' % (path))
            return
        if os.path.splitext(path)[1] != '.hex':
            cmd.fail('text="firmware file must be a .hex file (%s)"' % (path))
            return

        feeControl.FeeControl(sendImage=path)

        cmd.finish('')

    def setSerials(self, cmd):
        """ Set one or more serial numbers for the DAQ chain. """

        fee = self.actor.fee
        cmdKeys = cmd.cmd.keywords

        for name in 'ADC', 'PA0', 'CCD0', 'CCD1':
            if name in cmdKeys:
                val = cmdKeys[name].values[0]
                cmd.inform('text="setting %s serial number to %s"' % (name, val))
                try:
                    fee.logger.setLevel(5)
                    fee.unlockConfig()
                    fee.setSerial(name, val)
                finally:
                    fee.lockConfig()
                    fee.logger.setLevel(20)
                    
        keys = self.actor.fee.getCommandStatus('serial')
        self._status(cmd, keys)

        cmd.finish()
        
    def setVoltageCalibrations(self, cmd):
        """ Set some/all FEE voltage calibrations. """

        cmdKeys = cmd.cmd.keywords

        voltageArgs = OrderedDict()
        for k in cmdKeys:
            if k.name == 'setVoltageCalibrations':
                continue
            # cmd.debug('text="trying to set voltage calibration for %s (%s)"' % (k.name,
            #                                                                     k.name in cmdKeys))
            voltageArgs[k.name] = cmdKeys[k.name].values[0]
        try:
            cmd.inform('text="trying to set voltage calibrations: %s"' % (voltageArgs))
            self.actor.fee.setVoltageCalibrations(**voltageArgs)
        except Exception as e:
            cmd.fail('text="failed to set voltage calibrations: %s"' % (e))
            return
        
        cmd.finish()

        
