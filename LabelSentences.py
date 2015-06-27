import sublime, sublime_plugin
import re

# todo: ensure that sentence ending is followed by a sentence beginning (or EOF) without any text in between
# todo: '-' followed by a </p> without any text in between is a sentence ending
# todo: '…' followed by non-capital letter does not end sentence
# todo: ensure closing parentheses at end of sentence are included in span
# todo: ensure opening parentheses at start of sentence are included in span
# todo: "he said" or variants after speech should be included in sentence

# Plugin Globals
NoRegion = sublime.Region(-1, -1)
openTagRx = r"<\w[^>]+>"
closeTagRx = r"</\w+>"
tagRx = r"<[^>]+>"
startSentenceRx = r"\(?[“\"]?\(?[A-Z0-9]"
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
    "[”\"]?"        # sentence may end with a close quote
    "\)?"        # sentence may end with a close parenthesis
  ")"
  "(?!\w)"        # last character of sentence cannot be succeeded directly by a letter (catches first dot in abbreviations)
  "(?!\s[A-Z]\.)"  # exclude first dot in spaced initials such as "J. K. Rowling"
)
labelingSpanRx = r"<span id=\"s\d{5}\">"

class TestStuffCommand(sublime_plugin.TextCommand):

  def run(self, edit):
    v = self.view
    s = v.sel()
    start = _getNextSentenceStartAfter(self, s[0].begin())
    print(start)
    s.clear()
    s.add(sublime.Region(start, start))


# select the next sentence after the current selection
class SelectNextSentenceCommand(sublime_plugin.TextCommand):

  def run(self, edit):
    v = self.view
    s = v.sel()
    if len(s) > 0:
      r = s[0] # only support single selection for this command
      sentence = _findNextSentenceAfterPoint(self, r.begin()) if r.empty() else _findNextSentenceAfterRegion(self, r)

      if sentence is not None:
        print("found sentence: "+str(v.rowcol(sentence.begin()))+" - "+str(v.rowcol(sentence.end())))
        s.clear()
        s.add(sentence)
        v.show_at_center(sentence)

# surround the current selection with <span> opening and closing tags, with id="s00000"
class SurroundSelectionWithSpanCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    v = self.view
    for r in v.sel():
      selectionText = v.substr(r)
      if len(selectionText) > 0:
        # fail if selection already contains labeled span
        if re.search(labelingSpanRx, selectionText):
          print("selection already contains a labeled span")
          return
        # fail if selection is immediately surrounded by labeling span tags
        precedingOpeningSpan = _findLastOpeningTagBefore(self, "span", r.begin(), [])
        if precedingOpeningSpan.end() == r.begin() and \
          re.search(labelingSpanRx, v.substr(precedingOpeningSpan)):
          print("selection is already surrounded by a labeled span")
          return
        # surround region with labeled span tags
        surrounded = "<span id=\"s00000\">" + selectionText + "</span>"
        v.replace(edit, r, surrounded)

class SurroundNextSentenceWithSpanCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    v = self.view
    v.run_command("select_next_sentence")
    v.run_command("surround_selection_with_span")

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

def _findNextSentenceAfterPoint(self, point):
  v = self.view

  sentenceStart = _getNextSentenceStartAfter(self, point)
  if sentenceStart == -1: return None
  return _findSentenceStartingAt(self, sentenceStart)

# Find the sentence immediately following the sentence delineated by the given region.
# The command fails with an error message if non-space text is found
# between the end of the given region and the start of the next sentence.
def _findNextSentenceAfterRegion(self, region):
  v = self.view

  sentenceStart = _getNextSentenceStartAfter(self, region.end())
  if sentenceStart == -1: return None
  nextText = v.find(r"(\s*<[^>]+>)*\s*(?=[^<>\s])", region.end()).end()
  if nextText < sentenceStart:
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

  # ensure that opening tags have matching closing tags (and vice versa) inside sentence region
  correctedRegion = _expandRegionToEnsureMatchingTags(self, region)

  return correctedRegion


# find the position of last sentence ending in the given region,
# or the first one after it if no sentence end is contained within the region
def _lastSentenceEndInOrFirstOneAfterRegion(self, region):
  v = self.view

  pos = -1
  searchFrom = region.begin()
  regionEnd = region.end()
  while searchFrom <= region.end():
    newPos = _findEndOfSentenceStartingAt(self, searchFrom)
    if newPos == -1 or newPos == region.end():
      return newPos
    if pos < 0 or newPos <= region.end():
      pos = newPos
    searchFrom = newPos

  return pos

def _findEndOfSentenceStartingAt(self, sentenceStart):
  v = self.view

  candidate = v.find(endSentenceRx, sentenceStart).end()
  return candidate

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
    print("first match for '"+matchRx+"' in region = "+str(firstMatch))
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
    print("searching for "+tagName+" between "+str(v.rowcol(startPoint))+" and "+str(v.rowcol(endPoint)))
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
