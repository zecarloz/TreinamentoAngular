def getSniffer(url, cookie):
    import sys
    import os
    import string
    import time
    import re
    import json
    import threading
    import urllib
    import urllib2
    import xml.etree.ElementTree

    compat_str = unicode
    compiled_regex_type = type(re.compile(''))
    NO_DEFAULT = object()

    class UrlItem(threading.Thread):
        VIDEO_TITLE = 'title'
        VIDEO_DURATION = 'duration'
        VIDEO_PIC_LINK = 'pic'
        VIDEO_LIST = 'list'
        VIDEO_URL = 'url'
        VIDEO_FORMAT = 'format'
        VIDEO_QUALITY = 'quality'
        VIDEO_SIZE = 'size'
        def __init__(self, url, fmt= 'no', quality = 0, bitrate = 0, size = 0):
            threading.Thread.__init__(self)
            self.url = url
            self.fmt = fmt
            self.quality = quality
            self.bitrate = bitrate
            self.size = size
            self.isvalid = 0

        def getUrl(self):
            return self.url

        def getFormat(self):
            return self.fmt

        def getQuality(self):
            return self.quality

        def getBitrate(self):
            return self.bitrate

        def getSize(self):
            return self.size

        def isValid(self):
            return self.isvalid

        def run(self):
            req = urllib2.Request(self.url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/38.0.2125.111 Safari/537.36')
            try:
                r = urllib2.urlopen(req, timeout=30)
                headers = r.info()
                self.size = headers['Content-Length']
                self.isvalid = 1
            except urllib2.HTTPError, e:
                print self.url, 'response code : ' + str(e.code)
            except urllib2.URLError, e:
                print self.url, e.args
            except Exception, e:
                print self.url, e

    class ExtractorError(Exception):
        def __init__(self, msg):
            super(ExtractorError, self).__init__(msg)

    class RegexNotFoundError(ExtractorError):
        """Error when a regex didn't match"""
        pass

    import operator

    _OPERATORS = [
        ('|', operator.or_),
        ('^', operator.xor),
        ('&', operator.and_),
        ('>>', operator.rshift),
        ('<<', operator.lshift),
        ('-', operator.sub),
        ('+', operator.add),
        ('%', operator.mod),
        ('/', operator.truediv),
        ('*', operator.mul),
    ]
    _ASSIGN_OPERATORS = [(op + '=', opfunc) for op, opfunc in _OPERATORS]
    _ASSIGN_OPERATORS.append(('=', lambda cur, right: right))

    _NAME_RE = r'[a-zA-Z_$][a-zA-Z_$0-9]*'


    class JSInterpreter(object):
        def __init__(self, code, objects=None):
            if objects is None:
                objects = {}
            self.code = code
            self._functions = {}
            self._objects = objects

        def interpret_statement(self, stmt, local_vars, allow_recursion=100):
            if allow_recursion < 0:
                raise ExtractorError('Recursion limit reached')

            should_abort = False
            stmt = stmt.lstrip()
            stmt_m = re.match(r'var\s', stmt)
            if stmt_m:
                expr = stmt[len(stmt_m.group(0)):]
            else:
                return_m = re.match(r'return(?:\s+|$)', stmt)
                if return_m:
                    expr = stmt[len(return_m.group(0)):]
                    should_abort = True
                else:
                    # Try interpreting it as an expression
                    expr = stmt

            v = self.interpret_expression(expr, local_vars, allow_recursion)
            return v, should_abort

        def interpret_expression(self, expr, local_vars, allow_recursion):
            expr = expr.strip()

            if expr == '':  # Empty expression
                return None

            if expr.startswith('('):
                parens_count = 0
                for m in re.finditer(r'[()]', expr):
                    if m.group(0) == '(':
                        parens_count += 1
                    else:
                        parens_count -= 1
                        if parens_count == 0:
                            sub_expr = expr[1:m.start()]
                            sub_result = self.interpret_expression(
                                sub_expr, local_vars, allow_recursion)
                            remaining_expr = expr[m.end():].strip()
                            if not remaining_expr:
                                return sub_result
                            else:
                                expr = json.dumps(sub_result) + remaining_expr
                            break
                else:
                    raise ExtractorError('Premature end of parens in %r' % expr)

            for op, opfunc in _ASSIGN_OPERATORS:
                m = re.match(r'''(?x)
                    (?P<out>%s)(?:\[(?P<index>[^\]]+?)\])?
                    \s*%s
                    (?P<expr>.*)$''' % (_NAME_RE, re.escape(op)), expr)
                if not m:
                    continue
                right_val = self.interpret_expression(
                    m.group('expr'), local_vars, allow_recursion - 1)

                if m.groupdict().get('index'):
                    lvar = local_vars[m.group('out')]
                    idx = self.interpret_expression(
                        m.group('index'), local_vars, allow_recursion)
                    assert isinstance(idx, int)
                    cur = lvar[idx]
                    val = opfunc(cur, right_val)
                    lvar[idx] = val
                    return val
                else:
                    cur = local_vars.get(m.group('out'))
                    val = opfunc(cur, right_val)
                    local_vars[m.group('out')] = val
                    return val

            if expr.isdigit():
                return int(expr)

            var_m = re.match(
                r'(?!if|return|true|false)(?P<name>%s)$' % _NAME_RE,
                expr)
            if var_m:
                return local_vars[var_m.group('name')]

            try:
                return json.loads(expr)
            except ValueError:
                pass

            m = re.match(
                r'(?P<var>%s)\.(?P<member>[^(]+)(?:\(+(?P<args>[^()]*)\))?$' % _NAME_RE,
                expr)
            if m:
                variable = m.group('var')
                member = m.group('member')
                arg_str = m.group('args')

                if variable in local_vars:
                    obj = local_vars[variable]
                else:
                    if variable not in self._objects:
                        self._objects[variable] = self.extract_object(variable)
                    obj = self._objects[variable]

                if arg_str is None:
                    # Member access
                    if member == 'length':
                        return len(obj)
                    return obj[member]

                assert expr.endswith(')')
                # Function call
                if arg_str == '':
                    argvals = tuple()
                else:
                    argvals = tuple([
                        self.interpret_expression(v, local_vars, allow_recursion)
                        for v in arg_str.split(',')])

                if member == 'split':
                    assert argvals == ('',)
                    return list(obj)
                if member == 'join':
                    assert len(argvals) == 1
                    return argvals[0].join(obj)
                if member == 'reverse':
                    assert len(argvals) == 0
                    obj.reverse()
                    return obj
                if member == 'slice':
                    assert len(argvals) == 1
                    return obj[argvals[0]:]
                if member == 'splice':
                    assert isinstance(obj, list)
                    index, howMany = argvals
                    res = []
                    for i in range(index, min(index + howMany, len(obj))):
                        res.append(obj.pop(index))
                    return res

                return obj[member](argvals)

            m = re.match(
                r'(?P<in>%s)\[(?P<idx>.+)\]$' % _NAME_RE, expr)
            if m:
                val = local_vars[m.group('in')]
                idx = self.interpret_expression(
                    m.group('idx'), local_vars, allow_recursion - 1)
                return val[idx]

            for op, opfunc in _OPERATORS:
                m = re.match(r'(?P<x>.+?)%s(?P<y>.+)' % re.escape(op), expr)
                if not m:
                    continue
                x, abort = self.interpret_statement(
                    m.group('x'), local_vars, allow_recursion - 1)
                if abort:
                    raise ExtractorError(
                        'Premature left-side return of %s in %r' % (op, expr))
                y, abort = self.interpret_statement(
                    m.group('y'), local_vars, allow_recursion - 1)
                if abort:
                    raise ExtractorError(
                        'Premature right-side return of %s in %r' % (op, expr))
                return opfunc(x, y)

            m = re.match(
                r'^(?P<func>%s)\((?P<args>[a-zA-Z0-9_$,]+)\)$' % _NAME_RE, expr)
            if m:
                fname = m.group('func')
                argvals = tuple([
                    int(v) if v.isdigit() else local_vars[v]
                    for v in m.group('args').split(',')])
                if fname not in self._functions:
                    self._functions[fname] = self.extract_function(fname)
                return self._functions[fname](argvals)
            raise ExtractorError('Unsupported JS expression %r' % expr)

        def extract_object(self, objname):
            obj = {}
            obj_m = re.search(
                (r'(?:var\s+)?%s\s*=\s*\{' % re.escape(objname)) +
                r'\s*(?P<fields>([a-zA-Z$0-9]+\s*:\s*function\(.*?\)\s*\{.*?\}(?:,\s*)?)*)' +
                r'\}\s*;',
                self.code)
            fields = obj_m.group('fields')
            # Currently, it only supports function definitions
            fields_m = re.finditer(
                r'(?P<key>[a-zA-Z$0-9]+)\s*:\s*function'
                r'\((?P<args>[a-z,]+)\){(?P<code>[^}]+)}',
                fields)
            for f in fields_m:
                argnames = f.group('args').split(',')
                obj[f.group('key')] = self.build_function(argnames, f.group('code'))

            return obj

        def extract_function(self, funcname):
            func_m = re.search(
                r'''(?x)
                    (?:function\s+%s|[{;,]\s*%s\s*=\s*function|var\s+%s\s*=\s*function)\s*
                    \((?P<args>[^)]*)\)\s*
                    \{(?P<code>[^}]+)\}''' % (
                    re.escape(funcname), re.escape(funcname), re.escape(funcname)),
                self.code)
            if func_m is None:
                raise ExtractorError('Could not find JS function %r' % funcname)
            argnames = func_m.group('args').split(',')

            return self.build_function(argnames, func_m.group('code'))

        def call_function(self, funcname, *args):
            f = self.extract_function(funcname)
            return f(args)

        def build_function(self, argnames, code):
            def resf(args):
                local_vars = dict(zip(argnames, args))
                for stmt in code.split(';'):
                    res, abort = self.interpret_statement(stmt, local_vars)
                    if abort:
                        break
                return res
            return resf

    class Sniffer:
        def __init__(self, url, cookie):
            self.url = url
            self.ua=''
            self.cookie=cookie
            self.title=''
            self.pic=''
            self.duration=0
            self.video_list = None
            self.age_gate = False
            self.video_webpage = None
            self.dash_manifest_url = None
            self.decrypt_sig_func = None

        def start(self):
            try:
                try:
                    print 'begin _start'
                    self._start()
                except:
                    pass

                print 'end _start'
                # if len(self.video_list) == 0:
                #     self.requstKeepVid()

                if len(self.video_list) == 0:
                    return 0

                self.waitForCheckUrl()
                self.video_list.sort(key=lambda x:(x.getFormat(),x.getQuality()))

                return 1
            finally:
                try:
                    if sys.stdout:
                        sys.stdout.flush()
                        sys.stderr.flush()
                except:
                    pass




        def _start(self):
            get_info = 0
            self.video_list = list()
            print 'extract video id'
            rx = re.search(r"/watch?[^\s]*v=([^&\s]+)", self.url)
            if rx is None:
                rx = re.search(r"/v/([^?&\n\fv]+)", self.url)
                if rx is None:
                    print 'can\'t find video id.'
                    return 0

            vid = rx.group(1)
            print 'video id: %s' % vid
            self.url = 'http://www.youtube.com/watch?v=%s' % vid
            html = self.request(self.url)

            if html is None:
                return 0

            self.video_webpage = html
            self.getTitltAndThumb(html)
            self.getDurationFormHtml(html)

            rx0 = re.search(r"dashmpd\":\s*\"([^\"]+)", html)
            if rx0:
                self.dash_manifest_url = rx0.group(1).replace('\\', '')
                print 'dash_manifest_url: %s' % self.dash_manifest_url

            fmt_stream_map = []
            rx1 = re.search(r"url_encoded_fmt_stream_map\":\s*\"([^\"]+)", html)
            rx2 = re.search(r"adaptive_fmts\":\s*\"([^\"]+)", html)
            if (rx2 is None) and (rx1 is None):
                fmt_stream_map = self.getFmtStreamMap(vid)
                if fmt_stream_map is None:
                    print "can't find fmt_stream_map."
                    return 0
            else:
                if rx1:
                    fmt_stream_map += str.split(rx1.group(1), ',')
                if rx2:
                    fmt_stream_map += str.split(rx2.group(1), ',')

            player_url = None
            print 'get date from fmt_stream_map'
            for stream in fmt_stream_map:
                stream = urllib.unquote(stream)
                stream = stream.replace('\\u0026', '*')

                ## url
                if get_info is 1:
                    rx = re.search(r'url=([^&\*\s]+)', stream)
                else:
                    rx = re.search(r'url=([^\*\s]+)', stream)
                if rx is None:
                    continue

                stream_url = rx.group(1)

                ## signature
                sig = None
                rx = re.search(r'(\W|^)(sig|signature)=([^&\*\s]+)', stream)
                if rx is None:
                    print 'need signature'
                    rx = re.search(r'(\W|^)s=([^\*\s]+)', stream)
                    if rx:
                        print 'age_age:', self.age_gate
                        if not self.decrypt_sig_func:
                            if not self.age_gate:
                                jsplayer_url_json = self._search_regex(
                                    r'"assets":.+?"js":\s*("[^"]+")',
                                    html, u'JS player URL')
                                player_url = json.loads(jsplayer_url_json)
                            else:
                                player_url_json = self._search_regex(
                                    r'ytplayer\.config.*?"url"\s*:\s*("[^"]+")',
                                    html, 'age gate player URL')
                                player_url = json.loads(player_url_json)
                            #player_url = 'https://www.youtube.com/yts/jsbin/player-vfl8jhACg/en_US/base.js'
                            if player_url:
                                if player_url.find('vfl8jhACg')>-1:
                                    print 'replace vfl8jhACg to vflJ6jfXc'
                                    player_url = player_url.replace('vfl8jhACg', 'vflJ6jfXc')
                                if player_url.startswith('//'):
                                    player_url = 'https:' + player_url
                                elif not re.match(r'https?://', player_url):
                                    player_url = 'https://www.youtube.com' + player_url
                                print 'player: ' + player_url
                                jscode = self.request(player_url)
                                self.decrypt_sig_func = self._parse_sig_js(jscode)
                        if self.decrypt_sig_func:
                            sig = self.decrypt_sig_func(rx.group(2))
                        else:
                            sig = rx.group(2)
                else:
                    sig = rx.group(3)

                if sig:
                    stream_url = stream_url + '&signature=%s' % sig

                ## ext,quality
                rx = re.search(r'itag=(\d+)', stream)
                if rx is None:
                    continue
                itag = rx.group(1)

                info = self.getInfoFromItag(string.atoi(itag))
                if info is None:
                    continue
                self.addUrlItem(url=urllib.unquote(stream_url),fmt=info[1],quality=info[0],bitrate=info[2])

            # DASH AUDIO
            def decrypt_sig(mobj):
                s = mobj.group(1)
                dec_s = self.decrypt_sig_func(s)
                return '/signature/%s' % dec_s

            print 'get date from dash_manifest_url'

            self.dash_manifest_url = re.sub(r'/s/([\w\.]+)', decrypt_sig, self.dash_manifest_url)

            #dash_doc = xml.etree.ElementTree.fromstring(self.request(self.dash_manifest_url).encode('utf-8'))
            dashXml = self.request(self.dash_manifest_url)
            dash_doc = xml.etree.ElementTree.fromstring(dashXml.encode('utf-8'))

            formats = []
            for a in dash_doc.findall('.//{urn:mpeg:DASH:schema:MPD:2011}AdaptationSet'):
                mime_type = a.attrib.get('mimeType')
                for r in a.findall('{urn:mpeg:DASH:schema:MPD:2011}Representation'):
                    url_el = r.find('{urn:mpeg:DASH:schema:MPD:2011}BaseURL')
                    if url_el is None:
                        continue
                    if mime_type == 'text/vtt':
                        # TODO implement WebVTT downloading
                        pass
                    elif mime_type.startswith('audio/') or mime_type.startswith('video/'):
                        format_id = r.attrib['id']
                        stream_url = url_el.text

                        f = {
                            'format_id': format_id,
                            'url': stream_url,
                        }
                        try:
                            existing_format = next(
                                fo for fo in formats
                                if fo['format_id'] == format_id)
                        except StopIteration:
                            info = self.getInfoFromItag(string.atoi(format_id));
                            # info.update(f)
                            # formats.append(full_info)
                            #
                            if info is not None:
                                self.addUrlItem(url=stream_url,fmt=info[1],quality=info[0],bitrate=info[2])
                                self.addUrlItem(url=urllib.unquote(stream_url),fmt=info[1],quality=info[0],bitrate=info[2])
                        else:
                            existing_format.update(f)
            return 1

        def requstKeepVid(self):
            import hashlib
            from urllib import quote, urlencode
            def compat_urllib_parse_urlencode(query, doseq=0, encoding='utf-8'):
                def encode_elem(e):
                    if isinstance(e, dict):
                        e = encode_dict(e)
                    elif isinstance(e, (list, tuple,)):
                        list_e = encode_list(e)
                        e = tuple(list_e) if isinstance(e, tuple) else list_e
                    elif isinstance(e, compat_str):
                        e = e.encode(encoding)
                    return e

                def encode_dict(d):
                    return dict((encode_elem(k), encode_elem(v)) for k, v in d.items())

                def encode_list(l):
                    return [encode_elem(e) for e in l]

                return urlencode(encode_elem(query), doseq=doseq)
            print 'Begin requstKeepVid'
            host = 'http://srv1.keepvid.com/api/v2.php'
            data = compat_urllib_parse_urlencode({'url': self.url})
            mobj = re.search(r'url=(.+)', data)
            gethash = hashlib.md5((('%s_keepvid' % mobj.group(1))).encode('utf-8')).hexdigest()
            reqUrl = '%s?%s' % (host, urlencode({'url': self.url, 'gethash': gethash}))
            html = self.requestWithRef(reqUrl, "http://www.keepvid.com/")

            data = json.loads(html)
            print data['error']
            for value in data['download_links'].values():
                if value['type'].find('WEBM') != -1:
                    continue

                if value['type'].find('M4A') != -1:
                    fmt = 'MP4A'
                    bitrate = 128000
                    quality = 0
                    if value['quality'].find('128 kbps') != -1:
                        bitrate = 128000
                    if value['quality'].find('256 kbps') != -1:
                        bitrate = 256000
                else:
                    bitrate = 0
                    quality = 480
                    if value['quality'].find('144p') != -1:
                       quality = 144
                    if value['quality'].find('240p') != -1:
                       quality = 240
                    if value['quality'].find('360p') != -1:
                        quality = 360
                    if value['quality'].find('480p') != -1:
                        quality = 480
                    if value['quality'].find('720p') != -1:
                        quality = 720
                    if value['quality'].find('1080p') != -1:
                        quality = 1080
                    if value['quality'].find('1440p') != -1:
                        quality = 1440
                    if value['quality'].find('2160p') != -1:
                        quality = 2160
                    if value['quality'].find('3072p') != -1:
                        quality = 3072

                    if value['type'].find('FLV') != -1:
                        fmt = 'FLV'
                    if value['type'].find('3GP') != -1:
                        fmt = '3GP'
                    if value['type'].find('MP4') != -1:
                        fmt = 'MP4'
                        if value['quality'].find('(Video Only)') != -1:
                            fmt = 'MP4V'
                try:
                    self.addUrlItem(url=value['url'], fmt=fmt, quality=quality, bitrate=bitrate)
                except:
                    pass
            print 'end requstKeepVid'

        def requestWithRef(self, url, ref):
            try:
                req = urllib2.Request(url)
                req.add_header('User-Agent', 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1)')
                req.add_header('Cookie', self.cookie)
                req.add_header('Referer', ref)
                return urllib2.urlopen(req, timeout=30).read()
            except urllib2.HTTPError, e:
                print url, 'response code : ' + str(e.code)
            except urllib2.URLError, e:
                print url, e.args
                return None

        def request(self, url):
            print 'begin request url: %s ---------------------------------------------------' % url
            try:
                req = urllib2.Request(url)
                req.add_header('User-Agent', 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1)')
                req.add_header('Cookie', self.cookie)
                result = urllib2.urlopen(req, timeout=30).read()
                #print 'response html: %s' % result
                print 'end request url: %s ---------------------------------------------------' % url
                return result
            except urllib2.HTTPError, e:
                print 'response code : ' + str(e.code)
            except urllib2.URLError, e:
                print e.args
                return None

        def getFmtStreamMap(self, vid):
            html = None
            if re.search(r'player-age-gate-content">', self.video_webpage) is not None:
                self.age_gate = True
                data = urllib.urlencode({
                    'video_id': vid,
                    'eurl': 'https://youtube.googleapis.com/v/' + vid,
                    'sts': self._search_regex(
                        r'"sts"\s*:\s*(\d+)', self.video_webpage, 'sts', default=''),
                })
                video_info_url = 'http://www.youtube.com/get_video_info?' + data
                html = self.request(video_info_url)
            else:
                self.age_gate = False
                els = ['', '&el=detailpage','&el=embedded', '&el=vevo']
                for el in els:
                    html = self.request('http://www.youtube.com/get_video_info?video_id=%s%s&ps=default&eurl=&gl=US&hl=en' % (vid, el))
                    if html is None:
                        continue

            self.dash_manifest_url = urllib.unquote(re.search(r"dashmpd[\"]?[:=]\s*[\"]?([^\"&]+)", html).group(1))
            rx1 = re.search(r"url_encoded_fmt_stream_map[\"]?[:=]\s*[\"]?([^\"&]+)", html)
            rx2 = re.search(r"adaptive_fmts[\"]?[:=]\s*[\"]?([^\"&]+)", html)
            fmt_stream_map = []
            if rx1 or rx2:
                if rx1:
                    fmt_stream_map += str.split(rx1.group(1), '%2C')
                if rx2:
                    fmt_stream_map += str.split(rx2.group(1), '%2C')
                return fmt_stream_map
            return None

        def getDurationFormHtml(self, html):
            ## rx = re.search(r'<meta\s+(property|name)=("og:title"|"title")\s+content="([^>]+)"', html)
            try:
                rx = re.search(r'<meta\s+(property|name|itemprop)=("og:duration"|"duration")\s+content="([^>]+)"', html)
                m = re.findall(r'(\W*[0-9]+)\W*',rx.group(3))
                if len(m)==3:
                    self.duration = int(m[0])*3600+ int(m[1])*60+ int(m[2])
                elif len(m)==2 and "M" in rx.group(3)and "S" in rx.group(3):
                    self.duration = int(m[0]) * 60 + int(m[1])
                elif len(m)==2 and "H" in rx.group(3)and "M" in rx.group(3):
                    self.duration = int(m[0]) * 3600 + int(m[1]) * 60
                elif len(m)==2 and "H" in rx.group(3)and "S" in rx.group(3):
                    self.duration = int(m[0]) * 3600 + int(m[1])
                elif len(m)==1 and "S" in rx.group(3):
                    self.duration = int(m[0])
                elif len(m)==1 and "M" in rx.group(3):
                    self.duration = int(m[0])*60
                elif len(m)==1 and "H" in rx.group(3):
                    self.duration = int(m[0])*3600
            except:
                self.duration = 0

        def getTitltAndThumb(self, html):
            rx = re.search(r'<meta\s+(property|name)=("og:title"|"title")\s+content="([^>]+)"', html)
            if rx:
                self.title = urllib.unquote_plus(rx.group(3))

            rx = re.search(r'<meta\s+(property|name|itemprop)=("og:image"|"image")\s+content="([^>]+)"', html)
            if rx:
                self.pic = rx.group(3)

        def getInfoFromItag(self, itag):
            rez = None ##['0p', 'ERR']

            if itag == 46: rez = [1080,'WebM', 0]
            elif itag == 45: rez = [720,'WebM', 0]
            elif itag == 44: rez = [480,'WebM', 0]
            elif itag == 43: rez = [360,'WebM', 0]
            elif itag == 313: rez = [2160,'WebM', 0]

            elif itag == 38: rez = [3072,'MP4',0]
            elif itag == 37: rez = [1080,'MP4',0]
            elif itag == 22: rez = [720,'MP4',0]
            elif itag == 18: rez = [360,'MP4',0]

            elif itag == 266: rez = [2160,'MP4V',0]
            elif itag == 133: rez = [240,'MP4V',0]
            elif itag == 134: rez = [360,'MP4V',0]
            elif itag == 135: rez = [480,'MP4V',0]
            elif itag == 136: rez = [720,'MP4V',0]
            elif itag == 137: rez = [1080,'MP4V',0]
            elif itag == 138: rez = [2160,'MP4V',0]
            elif itag == 264: rez = [1440,'MP4V',0]
            elif itag == 298: rez = [720, 'MP4V', 60]
            elif itag == 299: rez = [1080, 'MP4V', 60]

            elif itag == 139: rez = [0, "MP4A", 48000]
            elif itag == 140: rez = [0, "MP4A", 128000]
            elif itag == 141: rez = [0, "MP4A", 256000]
            elif itag == 172: rez = [0, "MP4A", 192000]

            elif itag == 120: rez = [720,'FLV',0]
            elif itag == 35: rez = [480,'FLV',0]
            elif itag == 34: rez = [360,'FLV',0]
            elif itag == 6: rez = [270,'FLV',0]
            elif itag == 5: rez = [240,'FLV',0]

            elif itag == 36: rez = [240,'3GP',0]
            elif itag == 17: rez = [144,'3GP',0]

            return rez

        ## crack key
        def decryptSig(self, s):
            a = list(s)

            a = self.ri(a, 28)
            a.reverse()
            a = a[1:]
            a = self.ri(a, 26)

            a = self.ri(a, 40)
            a.reverse()
            a = a[1:]
            return ''.join(a)

        def ri(self, s, k):
            p = s
            c = p[0]
            idx = k % len(p)
            p[0] = p[idx]
            p[k] = c
            return p

        def getTitle(self):
            return self.title

        def getDuration(self):
            if self.duration == None:
                return 0
            return self.duration

        def getPic(self):
            if type(self.pic) is not type(str()):
                self.pic = str(self.pic)
            return self.pic

        def getList(self):
            needToRemoveIndex = []
            videoDict = {}
            index = 0
            for item in self.video_list:
                if item.getQuality() > 0:
                    if not videoDict.has_key(item.getQuality()):
                        videoDict[item.getQuality()] = [item.getBitrate(), index]
                    else:
                        if videoDict[item.getQuality()][0] == item.getBitrate():
                            needToRemoveIndex.append(index)
                            #needToRemoveIndex.append(videoDict[item.getQuality()][1])
                index += 1
            try:
                needToRemoveIndex.sort(reverse=True)
                for i in needToRemoveIndex:
                    del self.video_list[i]
            except:
                pass

            return self.video_list

        def addUrlItem(self, url, fmt, quality, bitrate):
            d = UrlItem(url, fmt, quality, bitrate)
            d.start()
            self.video_list.append(d)

        def waitForCheckUrl(self):
            for item in self.video_list:
                item.join()

        def _search_regex(self, pattern, string, name, default=NO_DEFAULT, fatal=True, flags=0, group=None):
            """
            Perform a regex search on the given string, using a single or a list of
            patterns returning the first matching group.
            In case of failure return a default value or raise a WARNING or a
            RegexNotFoundError, depending on fatal, specifying the field name.
            """
            if isinstance(pattern, (str, compat_str, compiled_regex_type)):
                mobj = re.search(pattern, string, flags)
            else:
                for p in pattern:
                    mobj = re.search(p, string, flags)
                    if mobj:
                        break

            if sys.stderr.isatty() and os.name != 'nt':
                _name = '\033[0;34m%s\033[0m' % name
            else:
                _name = name

            if mobj:
                if group is None:
                    # return the first matching group
                    return next(g for g in mobj.groups() if g is not None)
                else:
                    return mobj.group(group)
            elif default is not NO_DEFAULT:
                return default
            elif fatal:
                raise RegexNotFoundError('Unable to extract %s' % _name)
            else:
                #self._downloader.report_warning('unable to extract %s' % _name + bug_reports_message())
                return None

        def _parse_sig_js(self, jscode):
            funcname = self._search_regex(
                (r'(["\'])signature\1\s*,\s*(?P<sig>[a-zA-Z0-9$]+)\(',
                 r'\.sig\|\|(?P<sig>[a-zA-Z0-9$]+)\('),
                jscode, 'Initial JS player signature function name', group='sig')

            jsi = JSInterpreter(jscode)
            initial_function = jsi.extract_function(funcname)
            return lambda s: initial_function([s])

    def initLog(logFileName):
        if logFileName != '':
            dirName = os.path.dirname(logFileName)
            if not os.path.exists(dirName):
                os.makedirs(dirName)
            try:
                sys.stdout = open(logFileName, 'a')
                sys.stderr = open(logFileName, 'a')
            except:
                pass

    def createInstance(url, cookie='', fileName = ''):
        if fileName != '':
            initLog(fileName)
        return Sniffer(url, cookie)

    def test(url,cookie=''):
        sniffer = createInstance(url,cookie)
        sniffer.start()
        print 'title: ', sniffer.getTitle()
        print 'duration: ', sniffer.getDuration()
        print 'pic: ', sniffer.getPic()
        count = 0
        for item in sniffer.getList():
            if item.isValid():
                count += 1
                print "%s %d %d %s" % (item.getFormat(), item.getQuality(), item.getBitrate(), item.getUrl())
        print 'count: ', count

    # # test age gate
    #test('https://www.youtube.com/watch?v=z5esfyTYrn0')
    #
    # # test no sig
    ##test('https://www.youtube.com/watch?v=5qanlirrRWs')
    #
    # #test sig
    #test('https://www.youtube.com/watch?v=FsjwG3FQna4')
    # #test 256
    #test('https://www.youtube.com/watch?v=-4MhqIZokf0')
    # #test 2160
    #test('https://www.youtube.com/watch?v=LRFlg64lA2o')
    # #test 2160 Ex
    #test('https://www.youtube.com/watch?v=1m_sWJQm2fs')
    return createInstance(url, cookie)