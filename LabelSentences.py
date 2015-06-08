import sublime, sublime_plugin

# select the next sentence after the current selection
class SelectNextSentenceCommand(sublime_plugin.TextCommand):
  NoRegion = sublime.Region(-1, -1)
  endSentenceRx = (
    "("
      "("
        "("
          "(?<!Mr)(?<!Mrs)(?<!Ms)(?<!Dr)(?<!Sr)(?<!Jr)"  # exclude dots after common abbreviations
          "(?<![A-Z]\.[A-Z])(?<!\s[A-Z]\.\s[A-Z])"       # exclude dots after initials (doesn't catch first initial)
          "\.+"     # final punctuation is "."
        "|"         # or
          "[?!]+"   # final punctuation is ? or ! (possibly repeated)
        "|"         # or
          "…"       # final punctuation is ellipses character: …
        ")”?"       # (.?!…) may be followed by a close quote
      ")"
      "|"
        "-”"        # cut off dialogue ending (must end with close quote)
    ")"
    "(?!\w)"        # last character of sentence cannot be succeeded directly by a letter
    "(?! [A-Z]\.)"  # exclude first dot in spaced initials such as "J. K. Rowling"
  )

  def run(self, edit):
    v = self.view
    s = v.sel()
    newRegions = []
    for r in s:
      sentence = self._findNextSentenceFromRegion(r)
      if sentence is not None:
        print("found sentence: "+str(v.rowcol(sentence.begin()))+" - "+str(v.rowcol(sentence.end())))
        newRegions.append(sentence)

    if len(newRegions) > 0:
      s.clear()
      s.add_all(newRegions)
      v.show_at_center(newRegions[0])
    else:
      v.run_command("move_to", {"to": "eof", "extend": "false"})

  # find the next region that specifies a sentence beginning in or after the given region
  def _findNextSentenceFromRegion(self, region):
    v = self.view
    precedingDotPos = self._lastSentenceEndingInOrFirstOneAfterRegion(region)
    if precedingDotPos == -1:
      return None

    sentenceStart = self._getNextSentenceStartAfter(precedingDotPos)
    if sentenceStart == -1:
      return None

    firstWord = v.find("[A-Z0-9]", precedingDotPos).begin()
    sentenceEnd = v.find(self.endSentenceRx, sentenceStart).end()
    if sentenceEnd == -1:
      return None

    # continue searching for sentence end if sentence is 2 characters long: e.g. "A. first example"
    if sentenceEnd - firstWord == 2:
      sentenceEnd = v.find(self.endSentenceRx, sentenceEnd).end()

    region = sublime.Region(sentenceStart, sentenceEnd)

    # ensure that opening tags have matching closing tags (and vice versa) inside sentence region
    correctedRegion = self._expandRegionToEnsureMatchingTags(region)

    return correctedRegion

  # find the position of last sentence ending in the given region,
  # or the first one after it if no sentence end is contained within the region
  def _lastSentenceEndingInOrFirstOneAfterRegion(self, region):
    v = self.view

    pos = -1
    searchFrom = region.begin()
    regionEnd = region.end()
    while searchFrom <= region.end():
      newPos = v.find(self.endSentenceRx, searchFrom).end()
      if newPos == -1 or newPos == region.end():
        return newPos
      if pos < 0 or newPos <= region.end():
        pos = newPos
      searchFrom = newPos

    return pos

  # find the next sentence start position after the point specified in startAt
  # a sentence can only start in an xml text region (outside a tag)
  # and will be the first capital letter or number after a sentence end.
  def _getNextSentenceStartAfter(self, startAt):
    v = self.view

    nextTag = v.find("<[^>]+>", startAt)
    candidate = v.find("[A-Z0-9“]", startAt).begin()
    if nextTag.begin() == -1 or candidate < nextTag.begin():
      # candidate start position is before next tag, so it's definitely outside a tag
      return candidate
    else:
      # recursively search starting at end of next tag
      return self._getNextSentenceStartAfter(nextTag.end())

  # returns a list of regions that match the given regular expression in the given region
  def _findMatchesInRegion(self, matchRx, region):
    v = self.view

    nextMatch = v.find(matchRx, region.begin())
    if not nextMatch.empty() and nextMatch.end() <= region.end():
      subsequentRegion = sublime.Region(nextMatch.end(), region.end())
      subsequentMatches = self._findMatchesInRegion(matchRx, subsequentRegion)
      return [nextMatch] + subsequentMatches
    else:
      return []

  # returns a list of regions that delineate the opening xml tags (e.g. <span>) in the given region
  def _findOpeningTagsInRegion(self, region):
    return self._findMatchesInRegion("<(?!/)[^>]+>", region)

  # returns a list of regions that delineate the closing xml tags (e.g. <span>) in the given region
  def _findClosingTagsInRegion(self, region):
    return self._findMatchesInRegion("</[^>]+>", region)

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
    if self._regionsIntersectRegion(exclusions, match):
      return self._findFirstClosingTagAfter(tagName, match.end(), exclusions)
    else:
      return match

  # returns a region whose end is extended forward compared to `region` enough
  # such that all tags that open inside the region also close inside the region
  def _expandRegionToEncloseMatchingClosingTags(self, region):
    v = self.view
    openingTags = self._findOpeningTagsInRegion(region)
    openingTags.reverse() # need to add excluded regions from right to left
    exclusions = []
    lastClosingTagEnd = region.end()
    for openingTag in openingTags:
      tagName = v.substr(v.find("\w+", openingTag.begin()))
      closingTag = self._findFirstClosingTagAfter(tagName, openingTag.end(), exclusions)
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
        return self.NoRegion
      lastMatch = findLastMatchInRegion(sublime.Region(firstMatch.end(), region.end()))
      if not lastMatch.empty():
        return lastMatch
      if self._regionsIntersectRegion(exclusions, firstMatch):
        return self.NoRegion
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
          return self.NoRegion
        # continue searching in the block of 100 characters before this searchRegion
        return findLastBeforePoint(startPoint)
      return match

    return findLastBeforePoint(endingAt)

  # Returns a region whose beginning is extended backward compared to `region` enough
  # such that all tags that close inside the region also open inside the region.
  def _expandRegionToEncloseMatchingOpeningTags(self, region):
    v = self.view
    closingTags = self._findClosingTagsInRegion(region)

    exclusions = []
    firstOpeningTagBegin = region.begin()
    for closingTag in closingTags:
      tagName = v.substr(v.find("\w+", closingTag.begin()))
      openingTag = self._findLastOpeningTagBefore(tagName, closingTag.begin(), exclusions)
      newExclusion = sublime.Region(openingTag.begin(), closingTag.end())
      exclusions.append(newExclusion)
      firstOpeningTagBegin = min(firstOpeningTagBegin, openingTag.begin())
    return sublime.Region(firstOpeningTagBegin, region.end())

  # Returns a region whose beginning and end are extended outward compared to
  # `region` enough that all tags that open inside the region also close
  # inside the region and vice versa.
  def _expandRegionToEnsureMatchingTags(self, region):
    expanded = self._expandRegionToEncloseMatchingClosingTags(region)
    expanded = self._expandRegionToEncloseMatchingOpeningTags(expanded)
    return expanded

# surround the current selection with <span> opening and closing tags, with id="s00000"
class SurroundSelectionWithSpanCommand(sublime_plugin.TextCommand):
  def run(self, edit):
    v = self.view
    for r in v.sel():
      selectionText = v.substr(r)
      if len(selectionText) > 0:
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

