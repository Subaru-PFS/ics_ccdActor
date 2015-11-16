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
            ('raw', '@raw', self.raw),
            # ('mode', '@(erase|read|integrate)', self.mode),
            ('temps', '', self.temps),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
        )

    def raw(self, cmd):
        """ Send a raw FEE command. """

        cmdTxt = cmd.cmd.keywords['raw'].values[0]
        
        ret = self.actor.fee.rawCmd(cmdTxt, cmd)

    def temps(self, cmd, doFinish=True):
        """Report CCD and preamp temperatures. """
        
        ret = self.actor.fee.getTemps()
        cmd.inform('ccdTemps=%0.2f,%0.2f,%0.2f' % (ret[1], ret[2], ret[3]))
        if doFinish:
            cmd.finish()
            
