#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Module to check domain mailserver and/or user mail address
#
# Copyright (c) 2005 JAS
#
# Author: Petr Vokac <vokac@kmlinux.fjfi.cvut.cz>
#
# $Id$
#
import logging
import socket
from Base import Base, ParamError
from ListDyn import ListDyn
from tools import dnscache, smtplib


__version__ = "$Revision$"


class Verification(Base):
    """Module for mx, connection, domain and user verification. It
    check domain existence and then it try to establish SMTP
    connection with mailhost for the domain (MX, A or AAAA DNS records
    - see RFC2821, chapter 5).

    You can check if sender/recipient or whatever reasonable has
    correct DNS records as mailhost and try to connect to this server.

    Second option si to check if sender/recipient is accepted by
    remote mailserver. Be carefull when turning on verification and
    first read http://www.postfix.org/ADDRESS_VERIFICATION_README.html
    to see limitation and problem that can happen.

    Module arguments (see output of getParams method):
    param, timeout, type

    Check arguments:
        data ... all input data in dict

    Check returns:
        5 (15) .... user verification was successfull (hit pernament cache)
        4 (14) .... domain verification was successfull (hit pernament cache)
        3 (13) .... connection verification was successfull (hit pernament cache)
        2 (12) .... mx verification was successfull (hit pernament cache)
        1 (11) .... check succeeded according RFC (sender, recipient)
        0 ......... undefined (e.g. DNS error, SMTP error, ...)
        -1 (-11) .. check failed, mail format invalid
        -2 (-12) .. mx verification failed (hit pernament cache)
        -3 (-13) .. connection verification failed (hit pernament cache)
        -4 (-14) .. domain verification failed (hit pernament cache)
        -5 (-15) .. user verification failed (hit pernament cache)

    Examples:
        # sender domain verification
        modules['verification'] = ( 'Verification', { param="sender" } )
        # recipient user verification
        modules['verification'] = ( 'Verification', { param="recipient",
                                                      vtype="user" } )
    """

    CHECK_PERNAMENT_CACHE=10
    CHECK_RESULT_RFC=1
    CHECK_RESULT_DNS=1
    CHECK_RESULT_FORMAT=1
    CHECK_RESULT_SMTP=1
    CHECK_RESULT_MX=2
    CHECK_RESULT_CONN=3
    CHECK_RESULT_DOMAIN=4
    CHECK_RESULT_USER=5

    PARAMS = { 'param': ('string key for data item that should be verified (sender/recipient)', None),
               'timeout': ('set SMTP connection timeout', 20),
               'vtype': ('mx, connection, domain or user verification', 'mx'),
               'cacheDB': ('cache results in database (almost useless for mx verification)', False),
               'table': ('database table with persistent cache', 'verification'),
               'dbExpirePositive': ('positive result expiration time in db', 28*24*60*60),
               'dbExpireNegative': ('negative result expiration time in db', 3*60*60),
               'cachePositive': (None, 24*60*60),
               'cacheUnknown': (None, 15*60),
               'cacheNegative': (None, 60*60),
               }


    def __getUserDomain(self, value):
        if value == None or value == '':
            return None, None

        vtype = self.getParam('vtype')

        # create email address to check
        if value.find("@") != -1:
            user = value[:value.rfind('@')]
            domain = value[value.rfind('@')+1:]
        else:
            user = 'postmaster'
            domain = value
        if vtype == 'domain':
            user = 'postmaster'
        if vtype in [ 'mx', 'connection' ]:
            user = None

        return user, domain


    def start(self):
        if self.factory == None:
            raise ParamError("this module need reference to fatory and database connection pool")

        for attr in [ 'param', 'timeout', 'vtype', 'table', 'dbExpirePositive', 'dbExpireNegative' ]:
            if self.getParam(attr) == None:
                raise ParamError("parameter \"%s\" has to be specified for this module" % attr)

        table = self.getParam('table')
        vtype = self.getParam('vtype')
        #dbExpirePositive = self.getParam('dbExpirePositive')
        dbExpireNegative = self.getParam('dbExpireNegative')

        if vtype not in [ 'mx', 'connection', 'domain', 'user' ]:
            raise ParamError("vtype can be only domain or user")

        if self.getParam('cacheDB'):
            self.cacheDB = ListDyn("%s_persistent_cache" % (self.getName()), self.factory, table=table, param=["param"], retcols=["code", "codeEx"], mapping={ 'code': ('code', 'TINYINT') }, softExpire=dbExpireNegative*3/4, hardExpire=dbExpireNegative)
            self.cacheDB.start()


    def hashArg(self, data, *args, **keywords):
        param = self.getParam('param')
        paramValue = data.get(param, '')
        user, domain = self.__getUserDomain(paramValue)
        if user == None:
            if domain == None:
                return 0
            else:
                return hash("%s" % domain)
        else:
            return hash("%s@%s" % (user, domain))


    def check(self, data, *args, **keywords):
        param = self.getParam('param')
        paramValue = data.get(param, '')
        vtype = self.getParam('vtype')
        dbExpirePositive = self.getParam('dbExpirePositive')
        #dbExpireNegative = self.getParam('dbExpireNegative')

        # RFC 2821, section 4.1.1.2
        # empty MAIL FROM: reverse address may be null
        if param == 'sender' and paramValue == '':
            return Verification.CHECK_RESULT_RFC, "%s accept empty From address" % self.getId()

        # RFC 2821, section 4.1.1.3
        # see RCTP TO: grammar
        if param == 'recipient':
            reclc = paramValue.lower()
            if reclc == 'postmaster' or reclc[:11] == 'postmaster@':
                return Verification.CHECK_RESULT_RFC, "%s accept all mail to postmaster" % self.getId()

        user, domain = self.__getUserDomain(paramValue)
        if domain == None:
            expl = "%s: address for %s in unknown format: %s" % (self.getId(), param, paramValue)
            logging.getLogger().warn(expl)
            return -Verification.CHECK_RESULT_FORMAT, expl
        if vtype != 'user':
            paramValue = domain

        # look in pernament result cache
        cacheCode = 0
        if self.getParam('cacheDB'):
            cacheCode, cacheVal = self.cacheDB.check({ 'param': paramValue }, operation="check")
        if cacheCode > 0:
            cacheCode, cacheRes, cacheEx = cacheVal[0]
            if cacheRes > 0:
                cacheRes = Verification.CHECK_PERNAMENT_CACHE + cacheRes
            elif cacheRes < 0:
                cacheRes = -Verification.CHECK_PERNAMENT_CACHE + cacheRes
            if cacheCode != ListDyn.CHECK_SOFT_EXPIRED:
                return cacheRes, cacheEx

        # list of mailservers
        try:
            mailhosts = dnscache.getDomainMailhosts(domain, local=False)
        except Exception, e:
            if cacheCode > 0:
                return cacheRes, cacheEx
            return -Verification.CHECK_RESULT_DNS, "%s DNS failure: %s" % (self.getId(), e)
            
        if len(mailhosts) == 0:
            code = -Verification.CHECK_RESULT_MX
            codeEx = "%s: no mailhost for %s" % (self.getId(), domain)
            logging.getLogger().info(codeEx)
            if self.getParam('cacheDB'):
                self.cacheDB.check({ 'param': paramValue }, operation="add", value={ 'code': code, 'codeEx': codeEx })
            return code, codeEx

        if vtype == 'mx':
            code = Verification.CHECK_RESULT_MX
            codeEx = "%s: mailhost for %s exists" % (self.getId(), domain)
            logging.getLogger().info(codeEx)
            if self.getParam('cacheDB'):
                self.cacheDB.check({ 'param': paramValue }, operation="add", value={ 'code': code, 'codeEx': codeEx }, softExpire=dbExpirePositive*3/4, hardExpire=dbExpirePositive)
            return code, codeEx

        # if site has only one IP for mailserver, try to connect
        # two times, because in case the server has hight load
        # it can refuse new connection - so be aggressive and try
        # to connect one more time
        if len(mailhosts) == 1:
            mailhosts.append(mailhosts[0])
        maxMXToTry = 3
        for mailhost in mailhosts:
            # FIXME: how many MX try? timeout?
            logging.getLogger().debug("trying to check %s for %s@%s" % (mailhost, user, domain))
            code, codeEx = self.checkMailhost(mailhost, domain, user)
            logging.getLogger().debug("checking returned: %s (%s)" % (code, codeEx))
            if code != None and code != Verification.CHECK_UNKNOWN:
                break
            maxMXToTry -= 1
            if maxMXToTry <= 0:
                break

        if code == None or code == Verification.CHECK_UNKNOWN:
            if cacheCode > 0:
                return cacheRes, cacheEx
            # don't cache this result - it can signal some network problem
            # and we don't want to slowdown receiving next mail from such sites
            code = -Verification.CHECK_RESULT_SMTP
            if vtype == 'connection':
                code = -Verification.CHECK_RESULT_CONN
            elif vtype == 'domain':
                code = -Verification.CHECK_RESULT_DOMAIN
            elif vtype == 'user':
                code = -Verification.CHECK_RESULT_USER
            return code, "%s didn't get any result" % self.getId()

        # add new informations to pernament cache
        if self.getParam('cacheDB'):
            if code > 0:
                self.cacheDB.check({ 'param': paramValue }, operation="add", value={ 'code': code, 'codeEx': codeEx }, softExpire=dbExpirePositive*3/4, hardExpire=dbExpirePositive)
            elif code < 0:
                self.cacheDB.check({ 'param': paramValue }, operation="add", value={ 'code': code, 'codeEx': codeEx })

        return code, codeEx


    def checkMailhost(self, mailhost, domain, user):
        """Check if something listening for incomming SMTP connection
        for mailhost. For details about status that can occur during
        communication see RFC 2821, section 4.3.2"""

        param = self.getParam('param')
        timeout = self.getParam('timeout')
        try:
            conn = smtplib.SMTP(mailhost, timeout=timeout)
            if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
                conn.set_debuglevel(10)
            if user != None:
                code, retmsg = conn.helo()
                if code >= 400:
                    conn.quit()
                    conn.close()
                    if code >= 500:
                        return Verification.CHECK_FAILED, "%s verification HELO failed with code %s: %s" % (param, code, retmsg)
                    else:
                        return Verification.CHECK_UNKNOWN, "%s verification HELO failed with code %s: %s" % (param, code, retmsg)
                code, retmsg = conn.mail("postmaster@%s" % self.factory.getConfig('domain'))
                if code >= 400:
                    conn.quit()
                    conn.close()
                    if code >= 500:
                        return Verification.CHECK_FAILED, "%s verification HELO failed with code %s: %s" % (param, code, retmsg)
                    else:
                        return Verification.CHECK_UNKNOWN, "%s verification HELO failed with code %s: %s" % (param, code, retmsg)
                code, retmsg = conn.rcpt("%s@%s" % (user, domain))
                if code >= 400:
                    conn.quit()
                    conn.close()
                    if code >= 500:
                        return Verification.CHECK_FAILED, "%s verification HELO failed with code %s: %s" % (param, code, retmsg)
                    else:
                        return Verification.CHECK_UNKNOWN, "%s verification HELO failed with code %s: %s" % (param, code, retmsg)
                code, retmsg = conn.rset()
                conn.quit()
            conn.close()
            return Verification.CHECK_SUCCESS, "address verification success"
        except smtplib.SMTPException, err:
            msg = "SMTP communication with %s (%s) failed: %s" % (mailhost, domain, err)
            logging.getLogger().warn("%s: %s" % (self.getId(), msg))
            return Verification.CHECK_UNKNOWN, "address verification failed: %s" % msg
        except socket.error, err:
            msg = "socket communication with %s (%s) failed: %s" % (mailhost, domain, err)
            logging.getLogger().info("%s: %s" % (self.getId(), msg))
            return Verification.CHECK_UNKNOWN, "address verification failed: %s" % msg

        return Verification.CHECK_FAILED, "address verification failed."
