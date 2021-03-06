#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Check if client address is in various DNS blacklists and make sum
# of scores defined in spamassassin config files.
#
# Copyright (c) 2005 JAS
#
# Author: Petr Vokac <vokac@kmlinux.fjfi.cvut.cz>
#
# $Id$
#
import logging
from Base import Base, ParamError
from tools import dnsbl


__version__ = "$Revision$"


class DnsblScore(Base):
    """Check if client address and sender domain is in various DNS
    blacklists and make sum of scores that are defined in spamassassin
    config files. Returned result depends on parameter treshold (this
    module can return -1,0,1 or exact score if treshold is None).

    This module use tools.dnsbl.score to score mail. By default
    it uses all available checks, but you can specify your custom by
    listing their name in dnsbl parameter. You can list all valid
    names by calling `python tools/dnsbl.py --list`.

    Module arguments (see output of getParams method):
    dnsbl, treshold, params

    Check arguments:
        data ... all input data in dict

    Check returns:
        1 (positive) .... score > treshold or positive score
        0 ............... unknown error (e.g. DNS problems)
        -1 (negative) ... score < treshold or negative score

    Examples:
        # return blacklist score for client address
        modules['dnsbl1'] = ( 'DnsblScore', {} )
        # check if blacklist score for client address exceed defined treshold
        modules['dnsbl1'] = ( 'DnsblScore', { treshold=5 } )
    """

    PARAMS = { 'dnsbl': ('list of DNS blacklist to use', None),
               'treshold': ('treshold that define which score mean this module fail', None),
               'params': ('which params we should check', [ 'client_address', 'sender' ]),
               'cachePositive': (None, 6*60*60), # cache DNSBL results longer time
               'cacheUnknown': (None, 30*60),    # because it consume a lot of time
               'cacheNegative': (None, 12*60*60),# to make multiple DNS requests
               }


    def start(self):
        for attr in [ 'dnsbl' ]:
            if self.getParam(attr) == None:
                raise ParamError("parameter \"%s\" has to be specified for this module" % attr)

        dnsblNames = self.getParam('dnsbl')
        for dnsblName in dnsblNames:
            if not dnsbl.getInstance().has_config(dnsblName):
                raise ParamError("there is not %s dnsbl list in config file" % dnsblName)

        params = self.getParam('params', [])
        paramsNew = []
        for param in params:
            if param in [ 'client_address', 'client_name', 'reverse_client_name', 'sender', 'recipient' ]:
                paramsNew.append(param)
            else:
                logging.getLogger().warn("don't know how to score %s" % param)
        self.setParam('params', paramsNew)


    def hashArg(self, data, *args, **keywords):
        params = self.getParam('params', [])
        paramsVal = []
        for param in params:
            val = data.get(param, '')
            if param in [ 'sender', 'recipient' ]:
                if val.rfind("@") != -1:
                    val = val[val.rfind('@')+1:]
                else:
                    val = ''
            paramsVal.append("%s=%s" % (param, val))
        return hash("\n".join(paramsVal))


    def check(self, data, *args, **keywords):
        dnsblNames = self.getParam('dnsbl')
        treshold = self.getParam('treshold')
        params = self.getParam('params', [])

        score = 0
        for param in params:
            val = data.get(param, '')
            if param in [ 'sender', 'recipient' ]:
                if val.rfind("@") != -1:
                    val = val[val.rfind('@')+1:]
                else:
                    val = ''

            if param == 'client_address':
                resHit, resScore = dnsbl.score(val, None, dnsblNames)
                score += resScore
            else:
                resHit, resScore = dnsbl.score(None, val, dnsblNames)
                score += resScore

        if treshold == None:
            return score, "%s blacklist score" % self.getId()
        if score > treshold:
            return 1, "%s blacklist score exceeded treshold" % self.getId()
        else:
            return -1, "%s blacklist score did not exceeded treshold" % self.getId()

