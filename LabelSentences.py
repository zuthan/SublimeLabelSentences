import sublime, sublime_plugin

# select the next sentence after the current selection
class SelectNextSentenceCommand(sublime_plugin.TextCommand):
  endSentenceRx = (
    "("
      "("
        "("
          "(?<!Mr)(?<!Mrs)(?<!Ms)(?<!Dr)(?<!Sr)(?<!Jr)"  # exclude dots after common abbreviations
          "(?<![A-Z]\.[A-Z])(?<!\s[A-Z]\.\s[A-Z])"       # exclude dots after initials (doesn't catch first initial)
          "\.+"     # final punctuation is "."
        "|"         # or
          "[?!]+"   # final punctuation is ? or !
        ")”?"       # (.?!) may be followed by a close quote
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
        print("found sentence: %(sentence)s" % locals())
        newRegions.append(sentence)

    if len(newRegions) > 0:
      s.clear()
      s.add_all(newRegions)
      v.show_at_center(newRegions[0])
    else:
      v.run_command("move_to", {"to": "eof", "extend": "false"})

  # find the next region that specifies a sentence beginning after the current selection
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
    return sublime.Region(sentenceStart, sentenceEnd)

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

