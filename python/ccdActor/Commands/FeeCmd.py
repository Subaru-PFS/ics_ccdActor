#!/usr/bin/env python

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
            ('fee', 'configure', self.configure),
            ('fee', 'status [@(serial)] [@(temps)] [@(bias)] [@(voltage)] [@(offset)] [@(preset)]', self.status),
            ('fee', 'test1', self.test1),
            ('fee', 'setSerials [<ADC>] [<PA0>] [<CCD0>] [<CCD1>]', self.setSerials),
            
            # ('mode', '@(erase|read|integrate)', self.mode),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
                                        keys.Key("ADC", types.Int(),
                                                 help='the ADC serial number'),
                                        keys.Key("PA0", types.Int(),
                                                 help='the preamp serial number'),
                                        keys.Key("CCD0", types.String(),
                                                 help='the serial number for CCD 0'),
                                        keys.Key("CCD1", types.String(),
                                                 help='the serial number for CCD 1'),
        )

    def raw(self, cmd):
        """ Send a raw FEE command. """

        cmdTxt = cmd.cmd.keywords['raw'].values[0]
        
        ret = self.actor.fee.getRaw(cmdTxt)
        cmd.finish('text=%s' % (qstr('returned: %s' % (ret))))  

    def _status(self, cmd, keys):
        """ Actually generate the keywords for the passed in keys. """

        for k, v in keys.iteritems():
            k = k.replace('.', '_')
            try:
                float(v)
            except:
                v = qstr(v)
                
            cmd.inform('%s=%s' % (k,v))
        
    def status(self, cmd):
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
        
    def configure(self, cmd):
        """ Calibrate FEE DACs and load mode voltages. """

        fee = self.actor.fee

        cmd.inform('text="calibrating fee.... takes 30s or so..."')
        fee.calibrate()
        cmd.inform('text="fee calibrated..."')

        self.status(cmd)

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
        
        
