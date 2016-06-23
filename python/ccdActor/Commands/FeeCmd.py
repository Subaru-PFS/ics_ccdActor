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
            # ('mode', '@(erase|read|integrate)', self.mode),
        ]

        # Define typed command arguments for the above commands.
        self.keys = keys.KeysDictionary("ccd_fee", (1, 1),
        )

    def raw(self, cmd):
        """ Send a raw FEE command. """

        cmdTxt = cmd.cmd.keywords['raw'].values[0]
        
        ret = self.actor.fee.getRaw(cmdTxt)
	cmd.finish('text=%s' % (qstr('returned: %s' % (ret))))  

