#!/usr/bin/env python

from builtins import object
from past.builtins import reload

import time

import opscore.protocols.keys as keys
import opscore.protocols.types as types
from opscore.utility.qstr import qstr

import fpga.ccdFuncs as nbFuncs
reload(nbFuncs)

class TestCmd(object):

    def __init__(self, actor):
        # This lets us access the rest of the actor.
        self.actor = actor

        # Declare the commands we implement. When the actor is started
        # these are registered with the parser, which will call the
        # associated methods when matched. The callbacks will be
        # passed a single argument, the parsed and typed command.
        #
        self.vocab = [
            ('test', 'V0', self.testV0),
            ('test', 'SP', self.testSP),
            ('test', 'offsets', self.testOffsets),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
                                        )
        self.cam = 'b9'
        
    @property
    def fee(self):
        return self.actor.fee
    
    def testSP(self, cmd):
        """ Run the FEE/CCD/scope Sx/Px tests. """

        self.actor.commandSets['CcdCmd'].read(cmd, nrows=10, ncols=100,
                                              doModes=False,
                                              doFinish=False)
        cmd.finish()
        
    def testOffsets(self, cmd):
        """ Measure the offset gains. """

        self.actor.commandSets['CcdCmd'].read(cmd, nrows=10, ncols=100,
                                              doModes=False,
                                              doFinish=False)
        cmd.finish()
        
    def testV0(self, cmd):
        """ Run the FEE/CCD/scope V0 test. """

        cmd.inform('text="bringing fee up..."')
        self.feeUp(cmd)
        # In idle at this point
        cmd.inform('text="wiping..."')
        self.actor.commandSets['CcdCmd'].wipe(cmd,
                                              ncols=10, nrows=1,
                                              doFinish=False)
        time.sleep(0.5)         # "integrate"
        cmd.inform('text="reading..."')
        self.actor.commandSets['CcdCmd'].read(cmd, ncols=10, nrows=1,
                                              doFeeCards=False,
                                              doFinish=False)
        
        cmd.inform('text="bringing fee down..."')
        self.feeDown(cmd)

        cmd.finish()
        
    def powerFee(self, state, cmd):
        cmdString = "power %s fee" % (state)
        cmdVar = self.actor.cmdr.call(actor='xcu_%s' % self.cam, cmdStr=cmdString,
                                      forUserCmd=cmd, timeLim=5.0)
        if cmdVar.didFail:
            cmd.fail('text=%s' % (qstr('Failed to power fee %s' % (state))))
            return

    def feeDown(self, cmd):
        cmd.inform('text="internal fee powerdown..."')
        self.fee.powerDown()
        time.sleep(0.25)
        cmd.inform('text="PCM fee power off..."')
        self.powerFee('off', cmd)
    
    def feeUp0(self, cmd):
        self.powerFee('on', cmd)
        time.sleep(3.5)

    def feeUp1(self, cmd):
        self.actor.attachController('fee')

    def feeUp(self, cmd):
        self.feeUp0(cmd)
        self.feeUp1(cmd)
    
    def V0(self):
        self.feeUp0()
        self.feeUp1()
        self.fee.setMode('wipe')
        time.sleep(1)
        self.fee.setMode('expose')
        time.sleep(1)
        self.fee.setMode('read')
        self.actor.ccd.readImage(nrows=40, ncols=100, 
                                 clockFunc=pfsClocks, doSave=False)
        self.fee.setMode('erase')
        time.sleep(1)
        pcm.powerOff('fee')
        time.sleep(1)
    
