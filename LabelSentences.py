import sublime, sublime_plugin
import re

# Plugin Globals
NoRegion = sublime.Region(-1, -1)
openTagRx = r"<\w[^>]+>"
closeTagRx = r"</\w+>"
tagRx = r"<[^>]+>"
tagsNotAllowedInSpanRx = r"<(p|div|br)\b[^>]*>"

startSentenceRx = (
  r"("
      "[“\"(]+" # open quote or parenthesis
      "(<[^>]+>)*" # possibly followed by tags
    ")?" # (maybe)
    "[A-Z0-9]" # followed by a capital latter or digit
    "(?!\w*\s(said|asked|exclaimed|declared|remarked)\.)"
)
closeQuoteRx = r"[”\"’]"
closeQuoteOrParenRx = r"[”\"’)]"
closeQuoteBangOrEllipsesRx = r"(...|[…!”\"’])"

upToNextNonspaceTextRx = r"(\s*<[^>]+>)*\s*(?=[^<>\s])"
upToNextTextRx = r"(<[^>]+>)*(?!=<)"
endSentenceRx = (
  r"("
    "("
      "(?<!Mr)(?<!Mrs)(?<!Ms)(?<!Dr)(?<!Sr)(?<!Jr)"  # exclude dots after common abbreviations
      "(?<![A-Z]\.[A-Z])"           # exclude dots in doted abbreviations (doesn't catch first dot)
      "(?<!\s[A-Z]\.\s[A-Z])"       # exclude dots after initials (doesn't catch first initial)
      "\.+"     # final punctuation is "."
    "|"         # or
      "[?!]+"   # final punctuation is ? or ! (possibly repeated)
    "|"         # or
      "…"       # final punctuation is ellipses "…". The case of an ellipses followed by a lower case letter will be excluded in code.
    "|"
      " -"      # final punctuation is dash " -". The case of a dash not followed by a </p> will be excluded in code.
    ")"
    "[”\"’]?"    # sentence may end with a close quote
    "\)?"        # sentence may end with a close parentheses
  ")"
  "(?!\w)"        # last character of sentence cannot be succeeded directly by a letter (catches first dot in abbreviations)
  "(?!\s[A-Z]\.)"  # exclude first dot in spaced initials such as "J. K. Rowling"
)

labellingSpanOpenTagRx = r"<span id=\"s\d{5}\">"
labellingSpanRx = labellingSpanOpenTagRx + r"(.(?!</span>))+.</span>"

class TestStuffCommand(sublime_plugin.TextCommand):

  def run(self, edit):
    v = self.view
    s = v.sel()
    start = _getNextSentenceStartAfter(self, s[0].begin())
    s.clear()
    s.add(sublime.Region(start, start))

class SelectLabelledSentences(sublime_plugin.TextCommand):
  def run(self, edit):
    v = self.view
    s = v.sel()
    sentences = v.find_all(labellingSpanRx)
    s.clear()
    s.add_all(sentences)

# select the next sentence after the current selection
class SelectNextSentenceCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    _selectNextSentence(self, edit)

# surround the current selection with <span> opening and closing tags, with id="s00000"
class SurroundSelectionWithSpanCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    _surroundSelectionsWithSpan(self, edit)

class SurroundSelectionAndFindNextSentenceCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    v = self.view
    s = v.sel()
    if len(s) > 0:
      r = s[0] # only support single selection for this command
      if r.empty(): # selection is empty so select the next sentence after cursor
        sentence = _findNextSentenceAfterPoint(self, r.begin())
        _selectRegion(self, sentence)
      else: # we already have a selection
        # surround the current selection with labelling span unless it is already labeled
        if not _regionIsLabeled(self, r):
          _surroundRegionWithSpan(self, edit, r)

        # select the next sentence
        _selectNextSentence(self, edit)

class ReNumberSentenceTagsCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    v = self.view
    s = v.sel()
    tagIds = v.find_all("(?<=\"s)\d{5}")
    if len(tagIds) > 0:
      s.clear()
      s.add_all(tagIds)
      v.run_command("insert_nums", {"format": "1:1~0=5d", "quiet": True})

# ====== private helpers ======

def _selectRegion(self, region):
  v = self.view
  s = v.sel()

  print("select region: "+textPositionAsString(v, region.begin())+" - "+textPositionAsString(v, region.end()))
  s.clear()
  s.add(region)
  v.show_at_center(region)

# select the next sentence after the current selection
# return whether the operation succeeded
def _selectNextSentence(self, edit):
  v = self.view
  s = v.sel()
  if len(s) > 0:
    r = s[0] # only support single selection for this command
    sentence = _findNextSentenceAfterPoint(self, r.begin()) if r.empty() else _findNextSentenceAfterRegion(self, r)

    if sentence is not None:
      # print("found sentence: "+textPositionAsString(v, sentence.begin())+" - "+textPositionAsString(v, sentence.end()))
      _selectRegion(self, sentence)
      return True
    else:
      print("could not find another sentence after selection")
  else:
    print("this command only works with a single selection")
  return False

# surround the current selection with <span> opening and closing tags, with id="s00000"
# return whether the operation succeeded
def _surroundSelectionsWithSpan(self, edit):
  v = self.view
  for r in v.sel():
    if not _surroundRegionWithSpan(self, edit, r):
      return False
  return True

# returns True if the given region contains or is immediately preceded by a sentence labeling span
def _regionIsLabeled(self, region):
  v = self.view

  if region.empty():
    return False

  regionText = v.substr(region)
  # does region contain a labeled span?
  if re.search(labellingSpanOpenTagRx, regionText):
    return True
  # is region immediately preceded by labeling span tag?
  precedingOpeningSpan = _findLastOpeningTagBefore(self, "span", region.begin(), [])
  if precedingOpeningSpan.end() == region.begin() and \
    re.search(labellingSpanOpenTagRx, v.substr(precedingOpeningSpan)):
    return True
  return False

# surround the given region with <span> opening and closing tags, with id="s00000"
# return whether the operation succeeded
def _surroundRegionWithSpan(self, edit, region):
  v = self.view

  if not region.empty():
    regionText = v.substr(region)

    # don't surround if region is already labeled
    if _regionIsLabeled(self, region):
      print("selection is already labeled with a span")
      return False

    # fail if the region contains elements that can't be nested inside a span
    res = re.search(tagsNotAllowedInSpanRx, regionText)
    if res:
      print("elements of type '"+res.group(1)+"' are not allowed inside span elements")
      return False

    # surround region with labeled span tags
    surrounded = "<span id=\"s00000\">" + regionText + "</span>"
    v.replace(edit, region, surrounded)
    return True
  return False

# Find the next sentence starting after the given point
def _findNextSentenceAfterPoint(self, point):
  v = self.view

  sentenceStart = _getNextSentenceStartAfter(self, point)
  if sentenceStart == -1: return None
  return _findSentenceStartingAt(self, sentenceStart)

# returns the position of the next character of non-space text within the xml doc,
# starting from `searchFrom`
def _findNextNonspaceTextStart(view, searchFrom):
  return view.find(upToNextNonspaceTextRx, searchFrom).end()

# returns the position of the next character of text within the xml doc,
# starting from `searchFrom`
def _findNextTextStart(view, searchFrom):
  return view.find(upToNextTextRx, searchFrom).end()

# Find the sentence immediately following the sentence delineated by the given region.
# The command fails with an error message if non-space text is found
# between the end of the given region and the start of the next sentence.
def _findNextSentenceAfterRegion(self, region):
  v = self.view

  sentenceStart = _getNextSentenceStartAfter(self, region.end())
  if sentenceStart == -1: return None
  nextTextStart = _findNextNonspaceTextStart(v, region.end())
  if nextTextStart < sentenceStart:
    print("There is text between the end of the selection and the start of the next sentence.")
    return None
  return _findSentenceStartingAt(self, sentenceStart)

def _findSentenceStartingAt(self, sentenceStart):
  v = self.view

  firstWord = v.find("[A-Z0-9]", sentenceStart).begin()
  sentenceEnd = _findEndOfSentenceStartingAt(self, sentenceStart)
  if sentenceEnd == -1: return None

  # continue searching for sentence end if sentence is 2 characters long: e.g. "A. first example"
  if sentenceEnd - firstWord == 2:
    sentenceEnd = v.find(endSentenceRx, sentenceEnd).end()

  region = sublime.Region(sentenceStart, sentenceEnd)

  return _extendRegionToValidSentence(self, region)

def _findEndOfSentenceStartingAt(self, sentenceStart):
  v = self.view

  candidateR = v.find(endSentenceRx, sentenceStart)
  candidateStr = v.substr(candidateR)
  candidateEnd = candidateR.end()

  nextNonspaceTextStart = _findNextNonspaceTextStart(v, candidateEnd)

  # " -" followed by text before the end of the paragraph is not the end of a sentence
  nextCloseP = v.find(r"</p>", candidateEnd)
  if re.search(" -$", candidateStr):
    if nextNonspaceTextStart < nextCloseP.begin():
      print("dash inside paragraph")
      return _findEndOfSentenceStartingAt(self, candidateEnd)

  # if candidate ends with an ellipses or close quote that isn't followed by a sentence start, extend to next sentence end.
  nextSentenceStart = _getNextSentenceStartAfter(self, candidateEnd)
  if re.search(closeQuoteBangOrEllipsesRx+r"$", candidateStr):
    if nextNonspaceTextStart < nextSentenceStart:
      print("ellipses or close quote not followed by sentence start")
      return _findEndOfSentenceStartingAt(self, candidateEnd)

  return candidateEnd

def _extendRegionToValidSentence(self, region):
  v = self.view

  # ensure that opening tags have matching closing tags (and vice versa) inside sentence region
  correctedRegion = _expandRegionToEnsureMatchingTags(self, region)

  # if the next text after candidate end is a close quote or parentheses, extend to include it.
  trailingQuoteOrParen = _findTrailingCloseQuoteOrParenAt(v, correctedRegion.end())
  if trailingQuoteOrParen:
    correctedRegion = correctedRegion.cover(trailingQuoteOrParen)

  # if we had to make adjustments, some conditions may no longer be satisfied so run them again
  if correctedRegion != region:
    return _extendRegionToValidSentence(self, correctedRegion)

  return region

# if the next text after the given position is a string of close quote or close parentheses,
# return the region containing those characters
def _findTrailingCloseQuoteOrParenAt(v, position):
  nextTextStart = _findNextTextStart(v, position)
  closeQuoteOrParen = v.find(closeQuoteOrParenRx+r"+", nextTextStart)
  if nextTextStart == closeQuoteOrParen.begin():
    return closeQuoteOrParen
  return None

# find the next sentence start position after the point specified in startAt
# a sentence can only start in an xml text region (outside a tag)
# and will be the first capital letter or number after a sentence end.
def _getNextSentenceStartAfter(self, startAt):
  v = self.view

  # if startAt is inside a tag, move it to the end of the tag
  nextOpenBracket = v.find(r"<", startAt)
  nextCloseBracket = v.find(r">", startAt)
  if nextCloseBracket.begin() < nextOpenBracket.begin():
    startAt = nextCloseBracket.end()

  nextTag = v.find(tagRx, startAt)
  candidate = v.find(startSentenceRx, startAt).begin()
  if nextTag.begin() == -1 or candidate < nextTag.begin():
    # candidate start position is before next tag, so it's definitely outside a tag
    return candidate
  else:
    # recursively search starting at end of next tag
    return _getNextSentenceStartAfter(self, nextTag.end())

# returns a list of regions that match the given regular expression in the given region
def _findMatchesInRegion(self, matchRx, region):
  v = self.view

  nextMatch = v.find(matchRx, region.begin())
  if not nextMatch.empty() and nextMatch.end() <= region.end():
    subsequentRegion = sublime.Region(nextMatch.end(), region.end())
    subsequentMatches = _findMatchesInRegion(self, matchRx, subsequentRegion)
    return [nextMatch] + subsequentMatches
  else:
    return []

# returns a list of regions that delineate the opening xml tags (e.g. <span>) in the given region
def _findOpeningTagsInRegion(self, region):
  return _findMatchesInRegion(self, openTagRx, region)

# returns a list of regions that delineate the closing xml tags (e.g. <span>) in the given region
def _findClosingTagsInRegion(self, region):
  return _findMatchesInRegion(self, closeTagRx, region)

# returns a bool indicating whether the given `regions` intersect the `region`
def _regionsIntersectRegion(self, regions, region):
  for r in regions:
    if r.intersects(region):
      return True
  return False

# returns the region enclosing the first closing tag of type `tagName`
# that doesn't intersect any region in `exclusions`
# starting at position `startingAt`
def _findFirstClosingTagAfter(self, tagName, startingAt, exclusions):
  v = self.view
  matchRx = "</" + tagName + ">"
  match = v.find(matchRx, startingAt)
  if _regionsIntersectRegion(self, exclusions, match):
    return _findFirstClosingTagAfter(self, tagName, match.end(), exclusions)
  else:
    return match

# returns a region whose end is extended forward compared to `region` enough
# such that all tags that open inside the region also close inside the region
def _expandRegionToEncloseMatchingClosingTags(self, region):
  v = self.view
  openingTags = _findOpeningTagsInRegion(self, region)
  openingTags.reverse() # need to add excluded regions from right to left
  exclusions = []
  lastClosingTagEnd = region.end()
  for openingTag in openingTags:
    tagName = v.substr(v.find("\w+", openingTag.begin()))
    closingTag = _findFirstClosingTagAfter(self, tagName, openingTag.end(), exclusions)
    newExclusion = sublime.Region(openingTag.begin(), closingTag.end())
    exclusions.append(newExclusion)
    lastClosingTagEnd = max(lastClosingTagEnd, closingTag.end())
  return sublime.Region(region.begin(), lastClosingTagEnd)

# returns a region enclosing the last opening tag of type `tagName`
# that begins before `endingAt` and which doesn't intersect any of the
# regions in `exclusions`
def _findLastOpeningTagBefore(self, tagName, endingAt, exclusions):
  v = self.view
  matchRx = "<" + tagName + "\\b[^>]*>"

  # finds the last tag of type `tagName` starting in region `region`
  def findLastMatchInRegion(region):
    firstMatch = v.find(matchRx, region.begin())
    # print("first match for '"+matchRx+"' in region = "+str(firstMatch))
    if firstMatch.empty() or firstMatch.begin() > region.end():
      return NoRegion
    lastMatch = findLastMatchInRegion(sublime.Region(firstMatch.end(), region.end()))
    if not lastMatch.empty():
      return lastMatch
    if _regionsIntersectRegion(self, exclusions, firstMatch):
      return NoRegion
    return firstMatch

  # finds the region enclosing the last tag of type `tagName` ending before point `endingAt`
  def findLastBeforePoint(endPoint):
    v = self.view
    # initially search the 100 characters before endPoint
    startPoint = max(0, endPoint - 100)
    # print("searching for "+tagName+" between "+textPositionAsString(v, startPoint)+" and "+textPositionAsString(v, endPoint))
    searchRegion = sublime.Region(startPoint, endPoint)
    match = findLastMatchInRegion(searchRegion)
    if match.empty():
      if startPoint <= 0: # already searched back to beginning of file
        print("failed to find an opening tag of type '"+tagName+"' before position "+str(endPoint))
        return NoRegion
      # continue searching in the block of 100 characters before this searchRegion
      return findLastBeforePoint(startPoint)
    return match

  return findLastBeforePoint(endingAt)

# Returns a region whose beginning is extended backward compared to `region` enough
# such that all tags that close inside the region also open inside the region.
def _expandRegionToEncloseMatchingOpeningTags(self, region):
  v = self.view
  closingTags = _findClosingTagsInRegion(self, region)

  exclusions = []
  firstOpeningTagBegin = region.begin()
  for closingTag in closingTags:
    tagName = v.substr(v.find("\w+", closingTag.begin()))
    openingTag = _findLastOpeningTagBefore(self, tagName, closingTag.begin(), exclusions)
    newExclusion = sublime.Region(openingTag.begin(), closingTag.end())
    exclusions.append(newExclusion)
    firstOpeningTagBegin = min(firstOpeningTagBegin, openingTag.begin())
  return sublime.Region(firstOpeningTagBegin, region.end())

# Returns a region whose beginning and end are extended outward compared to
# `region` enough that all tags that open inside the region also close
# inside the region and vice versa.
def _expandRegionToEnsureMatchingTags(self, region):
  expanded = _expandRegionToEncloseMatchingClosingTags(self, region)
  expanded = _expandRegionToEncloseMatchingOpeningTags(self, expanded)
  return expanded

# Returns the view position in the form (row,col) where row and col are 1-indexed
def textPositionAsString(view, position):
  (row,col) = view.rowcol(position)
  return "("+str(row+1)+","+str(col+1)+")"
