#===============================================================================
# Copyright 2007 Matt Chaput
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#    http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#===============================================================================

"""
Classes and functions for turning a piece of text into
an indexable stream of "tokens" (usually equivalent to words). There are
three general types of classes/functions involved in analysis:

    - Tokenizers are always at the start of the text processing pipeline.
      They take a string and yield Token objects (actually, the same token
      object over and over, for performance reasons) corresponding to the
      tokens (words) in the text.
      
      Every tokenizer is simply a callable that takes a string and returns a
      generator of tokens.
      
    - Filters take the tokens from the tokenizer and perform various
      transformations on them. For example, the LowerCaseFilter converts
      all tokens to lowercase, which is usually necessary when indexing
      regular English text.
      
      Every filter is a callable that takes a token generator and returns
      a token generator.
      
    - Analyzers are convenience functions/classes that "package up" a
      tokenizer and zero or more filters into a single unit, so you
      don't have to construct the tokenizer-filter-filter-etc. pipeline
      yourself. For example, the StandardAnalyzer combines a RegexTokenizer,
      LowerCaseFilter, and StopFilter.
    
      Every analyzer is simply a callable that takes a string and returns a
      token generator.
"""

import re

from whoosh.lang.porter import stem

# Default list of stop words (words so common it's usually
# wasteful to index them). This list is used by the StopFilter
# class, which allows you to supply an optional list to override
# this one.

STOP_WORDS = frozenset(("the", "to", "of", "a", "and", "is", "in", "this",
                        "you", "for", "be", "on", "or", "will", "if", "can", "are",
                        "that", "by", "with", "it", "as", "from", "an", "when",
                        "not", "may", "tbd", "yet"))

# Token object

class Token(object):
    """
    Represents a "token" (usually a word) extracted from the source text
    being indexed.
    
    Because object instantiation in Python is slow, tokenizers should create
    ONE SINGLE Token object and YIELD IT OVER AND OVER, changing the attributes
    each time.
    
    This trick means that consumers of tokens (i.e. filters) must
    never try to hold onto the token object between loop iterations, or convert
    the token generator into a list.
    Instead, save the attributes between iterations, not the object::
    
        def RemoveDuplicatesFilter(self, stream):
            # Removes duplicate words.
            lasttext = None
            for token in stream:
                # Only yield the token if its text doesn't
                # match the previous token.
                if lasttext != token.text:
                    yield token
                lasttext = token.text
    
    The Token object supports the following attributes:
    
        - text (string): The text of this token.
        - original (string): The original text of the token, set by the tokenizer
          and never modified by filters.
        - positions (boolean): whether this token contains a position. If this
          is True, the 'pos' attribute should be set to the index of the token
          (e.g. for the first token, pos = 0, for the second token, pos = 1, etc.)
        - chars (boolean): whether this token contains character offsets. If this
          is True, the 'startchar' and 'endchar' attributes should be set to the
          starting character offset and the ending character offset of this token.
        - stopped (boolean): whether this token has been stopped by a stop-word
          filter (not currently used).
        - boosts (boolean): whether this token contains a per-token boost. If this
          is True, the 'boost' attribute should be set to the current boost factor.
    """
    
    __slots__ = ("positions", "chars", "boosts",
                 "original", "text", "pos", "startchar", "endchar",
                 "stopped", "boost")
    
    def __init__(self, positions, chars, boosts = False):
        """
        @param positions: Whether this token should have the token position in
            the 'pos' attribute.
        @param chars: Whether this token should have the token's character offsets
            in the 'startchar' and 'endchar' attributes.
        """
        
        self.positions = positions
        self.chars = chars
        self.boosts = boosts
        self.stopped = False
        self.boost = 1.0

# Tokenizers

def IDTokenizer(value, positions = False, chars = False,
                start_pos = 0, start_char = 0):
    """
    Yields the entire input string as a single token. For use
    in indexed but untokenized fields, such as a document's path.
    """
    
    t = Token(positions, chars)
    t.original = t.text = value
    if positions:
        t.pos = start_pos + 1
    if chars:
        t.startchar = start_char
        t.endchar = start_char + len(value)
    yield t
    

class RegexTokenizer(object):
    """
    Uses a regular expression to extract tokens from text.
    """
    
    _default_expression = re.compile("\w+", re.UNICODE)
    
    def __init__(self, expression = None):
        """
        @param expression: A compiled regular expression object. Each match
            of the expression equals a token. For example, the expression
            re.compile("[A-Za-z0-9]+") would give tokens that only contain
            letters and numbers. Group 0 (the entire matched text) is used
            as the text of the token. If you require more complicated handling
            of the expression match, simply write your own tokenizer.
        @type expression: re.RegexObject
        """
        
        self.expression = expression or self._default_expression
    
    def __call__(self, value, positions = False, chars = False,
                 start_pos = 0, start_char = 0):
        """
        @param value: The text to tokenize.
        @param positions: Whether to record token positions in the token.
        @param chars: Whether to record character offsets in the token.
        @param start_pos: The position number of the first token. For example,
            if you set start_pos=2, the tokens will be numbered 2,3,4,...
            instead of 0,1,2,...
        @param start_char: The offset of the first character of the first
            token. For example, if you set start_char=2, the text "aaa bbb"
            will have chars (2,5),(6,9) instead (0,3),(4,7).
        @type value: string
        """
        
        t = Token(positions, chars)
        
        for pos, match in enumerate(self.expression.finditer(value)):
            t.original = t.text = match.group(0)
            t.stopped = False
            if positions:
                t.pos = start_pos + pos
            if chars:
                t.startchar = start_char + match.start()
                t.endchar = start_char + match.end()
            yield t


class SpaceSeparatedTokenizer(RegexTokenizer):
    """
    Splits tokens by whitespace.
    """
    
    _default_expression = re.compile("[^ \t\r\n]+")


class CommaSeparatedTokenizer(RegexTokenizer):
    """
    Splits tokens by commas with optional whitespace.
    """
    
    _default_expression = re.compile("[^,]+")
    
    def __call__(self, value, positions = False, chars = False,
                 start_pos = 0, start_char = 0):
        t = Token(positions, chars)
        
        for pos, match in enumerate(self.expression.finditer(value)):
            t.original = t.text = match.group(0).strip()
            t.stopped = False
            if positions:
                t.pos = start_pos + pos
            if chars:
                t.startchar = start_char + match.start()
                t.endchar = start_char + match.end()
            yield t


class NgramTokenizer(object):
    """
    Splits input text into N-grams instead of words. For example,
    NgramTokenizer(3, 4)("hello") will yield token texts
    "hel", "hell", "ell", "ello", "llo".
    
    Note that this tokenizer does NOT use a regular expression
    to extract words, so the grams emitted by it will contain
    whitespace, punctuation, etc. You may want to add a custom filter
    to this tokenizer's output. Alternatively, if you only want
    sub-word grams without whitespace, you could use RegexTokenizer
    with NgramFilter instead.
    """
    
    def __init__(self, minsize, maxsize = None):
        """
        @param minsize: The minimum size of the N-grams.
        @param maxsize: The maximum size of the N-grams. If you omit
            this parameter, maxsize == minsize.
        """
        
        self.min = minsize
        self.max = maxsize or minsize
        
    def __call__(self, value, positions = False, chars = False,
                 start_pos = 0, start_char = 0):
        inlen = len(value)
        t = Token(positions, chars)
        
        pos = start_pos
        for start in xrange(0, inlen - self.min):
            for size in xrange(self.min, self.max + 1):
                end = start + size
                if end > inlen: continue
                
                t.stopped = False
                if positions:
                    t.pos = pos
                if chars:
                    t.startchar = start_char + start
                    t.endchar = start_char + end
                
                yield t
            pos += 1
                    

# Filters

def PassFilter(tokens):
    """
    An identity filter: passes the tokens through untouched.
    """
    
    for t in tokens:
        yield t


class NgramFilter(object):
    """
    Splits token text into N-grams. For example,
    NgramFilter(3, 4), for token "hello" will yield token texts
    "hel", "hell", "ell", "ello", "llo".
    """
    
    def __init__(self, minsize, maxsize = None):
        """
        @param minsize: The minimum size of the N-grams.
        @param maxsize: The maximum size of the N-grams. If you omit
            this parameter, maxsize == minsize.
        """
        
        self.min = minsize
        self.max = maxsize or minsize
        
    def __call__(self, tokens):
        for t in tokens:
            text, chars = t.text, t.chars
            if chars:
                startchar = t.startchar
            # Token positions don't mean much for N-grams,
            # so we'll leave the token's original position
            # untouched.
            
            for start in xrange(0, len(text) - self.min):
                for size in xrange(self.min, self.max + 1):
                    end = start + size
                    if end > len(text): continue
                    
                    t.text = text[start:end]
                    
                    if chars:
                        t.startchar = startchar + start
                        t.endchar = startchar + end
                        
                    yield t


class StemFilter(object):
    """
    Stems (removes suffixes from) the text of tokens using the Porter stemming
    algorithm. Stemming attempts to reduce multiple forms of the same root word
    (for example, "rendering", "renders", "rendered", etc.) to a single word in
    the index.
    
    Note that I recommed you use a strategy of morphologically expanding the
    query terms (see query.Variations) rather than stemming the indexed words.
    """
    
    def __init__(self, ignore = None):
        """
        @param ignore: a collection of words that should not be stemmed. This
            is converted into a frozenset. If you omit this argument, all tokens
            are stemmed.
        @type ignore: sequence 
        """
        
        self.cache = {}
        if ignore is None:
            self.ignores = frozenset()
        else:
            self.ignores = frozenset(ignore)
    
    def clear(self):
        """
        This filter memoizes previously stemmed words to greatly speed up
        stemming. This method clears the cache of previously stemmed words.
        """
        self.cache.clear()
    
    def __call__(self, tokens):
        cache = self.cache
        ignores = self.ignores
        
        for t in tokens:
            if t.stopped:
                yield t
                continue
            
            text = t.text
            if text in ignores:
                yield t
            elif text in cache:
                t.text = cache[text]
                yield t
            else:
                t.text = s = stem(text)
                cache[text] = s
                yield s


_camel_exp = re.compile("[A-Z][a-z]*|[a-z]+|[0-9]+")
def CamelFilter(tokens):
    """
    Splits CamelCased words into multiple words. For example,
    the string "getProcessedToken" yields tokens
    "getProcessedToken", "get", "Processed", and "Token".
    
    Obviously this filter needs to precede LowerCaseFilter in a filter
    chain.
    """
    
    for t in tokens:
        yield t
        text = t.text
        
        if text and not text.islower() and not text.isupper() and not text.isdigit():
            chars = t.chars
            if chars:
                oldstart = t.startchar
            
            for match in _camel_exp.finditer(text):
                sub = match.group(0)
                if sub != text:
                    t.text = sub
                    if chars:
                        t.startchar = oldstart + match.start()
                        t.endchar = oldstart + match.end()
                    yield t


_underscore_exp = re.compile("[A-Z][a-z]*|[a-z]+|[0-9]+")
def UnderscoreFilter(tokens):
    """
    Splits words with underscores into multiple words. For example,
    the string "get_processed_token" yields tokens
    "get_processed_token", "get", "processed", and "token".
    
    Obviously you should not split words on underscores in the
    tokenizer if you want to use this filter.
    """
    
    for t in tokens:
        yield t
        text = t.text
        
        if text:
            chars = t.chars
            if chars:
                oldstart = t.startchar
            
            for match in _underscore_exp.finditer(text):
                sub = match.group(0)
                if sub != text:
                    t.text = sub
                    if chars:
                        t.startchar = oldstart + match.start()
                        t.endchar = oldstart + match.end()
                    yield t


class StopFilter(object):
    """
    Removes "stop" words (words too common to index) from
    the stream.
    """

    def __init__(self, stoplist = STOP_WORDS, minsize = 2):
        """
        @param stoplist: A collection of words to remove from the stream.
            This is converted to a frozenset. The default is a list of
            common stop words.
        @param minsize: The minimum length of token texts. Tokens with
            text smaller than this will be stopped.
        @type stoplist: sequence
        """
        
        if stoplist is None:
            self.stops = frozenset()
        else:
            self.stops = frozenset(stoplist)
        self.min = minsize
    
    def __call__(self, tokens):
        stoplist = self.stops
        minsize = self.min
        
        for t in tokens:
            text = t.text
            if len(text) >= minsize and text not in stoplist:
                yield t


def LowerCaseFilter(tokens):
    """
    Uses str.lower() to lowercase token text. For example, tokens
    "This","is","a","TEST" become "this","is","a","test".
    """
    
    for t in tokens:
        t.text = t.text.lower()
        yield t

# Analyzers

class Analyzer(object):
    """
    Abstract base class for analyzers.
    """
    
    def __repr__(self):
        return "%s()" % self.__class__.__name__

    def __call__(self, value):
        raise NotImplementedError


class IDAnalyzer(Analyzer):
    """
    Yields the original text as a single token. This is useful for fields
    you don't want to tokenize, such as the path of a file.
    """
    
    def __init__(self, strip = True):
        """
        @param strip: Whether to use str.strip() to strip whitespace
            from the value before yielding it as a token.
        @type strip: boolean
        """
        self.strip = strip
    
    def __call__(self, value, **kwargs):
        if self.strip: value = value.strip()
        return IDTokenizer(value, **kwargs)


class SpaceSeparatedAnalyzer(Analyzer):
    """
    Parses space-separated tokens.
    """
    
    def __init__(self):
        self.tokenizer = SpaceSeparatedTokenizer()
    
    def __call__(self, value, **kwargs):
        return self.tokenizer(value, **kwargs)


class CommaSeparatedAnalyzer(Analyzer):
    """
    Parses comma-separated tokens (with optional whitespace surrounding
    the commas).
    """
    
    def __init__(self):
        self.tokenizer = CommaSeparatedTokenizer()
        
    def __call__(self, value, **kwargs):
        return self.tokenizer(value, **kwargs)


class SimpleAnalyzer(Analyzer):
    """
    Uses a RegexTokenizer and applies a LowerCaseFilter.
    """
    
    def __init__(self):
        self.tokenizer = RegexTokenizer()
        
    def __call__(self, value, **kwargs):
        return LowerCaseFilter(self.tokenizer(value, **kwargs))


class StandardAnalyzer(Analyzer):
    """
    Uses a RegexTokenizer and applies a LowerCaseFilter and StopFilter.
    """
    
    def __init__(self, stoplist = STOP_WORDS, minsize = 2):
        """
        @param stoplist: See analysis.StopFilter.
        @param minsize: See analysis.StopFilter.
        """
        
        self.tokenizer = RegexTokenizer()
        
        if stoplist is None:
            self.stopper = PassFilter
        else:
            self.stopper = StopFilter(stoplist = stoplist, minsize = minsize)
        
    def __call__(self, value, **kwargs):
        return self.stopper(LowerCaseFilter(
                            self.tokenizer(value, **kwargs)))


class FancyAnalyzer(Analyzer):
    """
    Uses a RegexTokenizer and applies a CamelFilter,
    UnderscoreFilter, LowerCaseFilter, and StopFilter.
    """
    
    def __init__(self, stoplist = STOP_WORDS, minsize = 2):
        """
        @param stoplist: See analysis.StopFilter.
        @param minsize: See analysis.StopFilter.
        """
        
        self.tokenizer = RegexTokenizer()
        self.stopper = StopFilter(stoplist = stoplist, minsize = minsize)
        
    def __call__(self, value, **kwargs):
        return self.stopper(UnderscoreFilter(
                            LowerCaseFilter(
                            CamelFilter(
                            self.tokenizer(value, **kwargs)))))


class NgramAnalyzer(Analyzer):
    """
    Uses an NgramTokenizer and applies a LowerCaseFilter.
    """
    
    def __init__(self, minsize, maxsize = None):
        """
        See analysis.NgramTokenizer.
        """
        self.tokenizer = NgramTokenizer(minsize, maxsize = maxsize)
        
    def __call__(self, value, positions = False, chars = False):
        return LowerCaseFilter(self.tokenizer(value,
                                              positions = positions, chars = chars))


if __name__ == '__main__':
    pass





