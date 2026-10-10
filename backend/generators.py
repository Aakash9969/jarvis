"""
Local content generation.

When a valid LLM key is configured the model writes document contents.  When
it is not, these templates keep document creation genuinely useful instead of
producing empty files.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------- #
# Python programs
# --------------------------------------------------------------------------- #
_PROGRAMS: dict[str, str] = {}


def _program(name: str, body: str) -> None:
    _PROGRAMS[name] = body.strip("\n") + "\n"


_program("binary search", '''
def binary_search(items, target):
    """Return the index of target in a sorted list, or -1 if absent."""
    low, high = 0, len(items) - 1
    while low <= high:
        mid = (low + high) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1


if __name__ == "__main__":
    numbers = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
    target = int(input("Number to find: "))
    index = binary_search(numbers, target)
    print(f"Found at index {index}" if index != -1 else "Not found")
''')

_program("linear search", '''
def linear_search(items, target):
    for index, value in enumerate(items):
        if value == target:
            return index
    return -1


if __name__ == "__main__":
    numbers = [12, 5, 8, 23, 16, 2]
    target = int(input("Number to find: "))
    print(linear_search(numbers, target))
''')

_program("bubble sort", '''
def bubble_sort(items):
    values = list(items)
    for i in range(len(values) - 1):
        swapped = False
        for j in range(len(values) - 1 - i):
            if values[j] > values[j + 1]:
                values[j], values[j + 1] = values[j + 1], values[j]
                swapped = True
        if not swapped:
            break
    return values


if __name__ == "__main__":
    print(bubble_sort([5, 1, 4, 2, 8]))
''')

_program("fibonacci", '''
def fibonacci(n, memo=None):
    """Return the n-th Fibonacci number using memoised recursion."""
    memo = memo if memo is not None else {}
    if n < 2:
        return n
    if n not in memo:
        memo[n] = fibonacci(n - 1, memo) + fibonacci(n - 2, memo)
    return memo[n]


if __name__ == "__main__":
    print([fibonacci(i) for i in range(10)])
''')

_program("factorial", '''
def factorial(n):
    if n < 0:
        raise ValueError("n must be non-negative")
    result = 1
    for value in range(2, n + 1):
        result *= value
    return result


if __name__ == "__main__":
    print(factorial(5))
''')

_program("palindrome", '''
def is_palindrome(text):
    cleaned = "".join(ch.lower() for ch in text if ch.isalnum())
    return cleaned == cleaned[::-1]


if __name__ == "__main__":
    print(is_palindrome("A man, a plan, a canal: Panama"))
''')

_program("prime", '''
def is_prime(n):
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0:
        return False
    divisor = 3
    while divisor * divisor <= n:
        if n % divisor == 0:
            return False
        divisor += 2
    return True


if __name__ == "__main__":
    print([n for n in range(2, 50) if is_prime(n)])
''')

_program("fizzbuzz", '''
for number in range(1, 101):
    if number % 15 == 0:
        print("FizzBuzz")
    elif number % 3 == 0:
        print("Fizz")
    elif number % 5 == 0:
        print("Buzz")
    else:
        print(number)
''')

_program("reverse string", '''
def reverse(text):
    return text[::-1]


if __name__ == "__main__":
    print(reverse("hello world"))
''')

# --------------------------------------------------------------------------- #
# Study plans & notes
# --------------------------------------------------------------------------- #
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def study_plan(topic: str) -> str:
    topic = topic.strip()
    label = topic.title() if topic and topic.lower() not in ("study plan", "your subject") else "Study Plan"
    start = date.today()
    heading = "# 7-Day Study Plan" if label == "Study Plan" else f"# 7-Day Study Plan - {label}"
    lines = [
        heading,
        f"Created {start:%d %B %Y} by JARVIS",
        "",
        "Goal: build steady, active understanding instead of passive reading.",
        "",
        "| Day | Date | Focus | Session |",
        "| --- | --- | --- | --- |",
    ]
    subject = "your subject" if label == "Study Plan" else label
    focus = [
        f"{subject}: big picture and vocabulary",
        f"Core concepts of {subject}",
        f"Worked examples for {subject}",
        "Practice problems (no notes)",
        "Fix weak areas from yesterday",
        "Full revision + flashcards",
        "Mini self-test and review",
    ]
    session = [
        "45 min read + mind map",
        "60 min study + 20 min recall",
        "90 min problem solving",
        "60 min timed practice",
        "45 min targeted revision",
        "60 min active recall",
        "45 min mock test",
    ]
    for offset, day in enumerate(_DAYS):
        current = start + timedelta(days=offset)
        lines.append(f"| {day} | {current:%d %b} | {focus[offset]} | {session[offset]} |")

    lines += [
        "",
        "## Daily routine",
        "1. 10 min - recall yesterday from memory (no notes).",
        "2. 40-60 min - new material, one concept at a time.",
        "3. 20 min - solve problems with the book closed.",
        "4. 10 min - write 3 questions you still cannot answer.",
        "",
        "## Progress log",
        "- [ ] Day 1",
        "- [ ] Day 2",
        "- [ ] Day 3",
        "- [ ] Day 4",
        "- [ ] Day 5",
        "- [ ] Day 6",
        "- [ ] Day 7",
        "",
        "Tips: study in 25-minute blocks, teach each topic out loud once, and "
        "review mistakes the next morning.",
    ]
    return "\n".join(lines)


def notes(topic: str) -> str:
    topic = topic.strip() or "New Topic"
    return "\n".join([
        f"# Notes - {topic.title()}",
        f"Created {datetime.now():%d %B %Y, %H:%M} by JARVIS",
        "",
        "## Key ideas",
        "- ",
        "",
        "## Definitions",
        "| Term | Meaning |",
        "| --- | --- |",
        "|  |  |",
        "",
        "## Examples",
        "```",
        "",
        "```",
        "",
        "## Questions to revisit",
        "- [ ] ",
        "",
        "## Summary",
        "",
    ])


def todo_list(items: list[str] | None = None) -> str:
    items = items or ["Review today's notes", "Practise one problem set", "Plan tomorrow"]
    lines = [f"# To-Do - {date.today():%d %B %Y}", ""]
    lines += [f"- [ ] {item}" for item in items]
    lines += ["", "## Completed", ""]
    return "\n".join(lines)


def outline(title: str) -> str:
    title = title.strip() or "Document"
    return "\n".join([
        f"# {title.title()}",
        f"_{date.today():%d %B %Y}_",
        "",
        "## Introduction",
        "",
        "## Main points",
        "1. ",
        "2. ",
        "3. ",
        "",
        "## Conclusion",
        "",
        "## References",
        "- ",
    ])


def default_document(subject: str) -> str:
    subject = subject.strip() or "Document"
    return "\n".join([
        f"# {subject.title()}",
        f"Created {datetime.now():%d %B %Y, %H:%M} by JARVIS",
        "",
        subject.capitalize() + " ...",
        "",
        "- Point one",
        "- Point two",
        "- Point three",
        "",
    ])


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def python_program(request: str) -> str | None:
    """Pick a bundled program for a request like 'binary search program'."""
    lowered = request.lower()
    for name, body in _PROGRAMS.items():
        if name in lowered:
            return body
    # also match "binary search" written as "binarysearch"
    compact = re.sub(r"[^a-z]", "", lowered)
    for name, body in _PROGRAMS.items():
        if re.sub(r"[^a-z]", "", name) in compact:
            return body
    return None


def generate_content(request: str, *, filename: str = "") -> tuple[str, str]:
    """
    Produce content for a document request.

    Returns ``(kind, content)``.
    """
    text = request if (filename and filename.lower() in request.lower()) else f"{request} {filename}".strip()
    lowered = text.lower()

    if any(word in lowered for word in ("study plan", "studyplan", "revision plan", "timetable", "schedule", "7-day", "7 day")):
        topic = _extract_topic(lowered, ("study plan", "studyplan", "revision plan", "timetable", "schedule", "for", "on", "about"))
        return "study plan", study_plan(topic)

    if any(word in lowered for word in ("todo", "to-do", "task list", "checklist")):
        return "to-do list", todo_list()

    if any(word in lowered for word in ("outline", "report", "essay", "article")):
        topic = _extract_topic(lowered, ("outline", "report", "essay", "article", "on", "about", "for"))
        return "outline", outline(topic)

    if any(word in lowered for word in ("notes", "note")):
        topic = _extract_topic(lowered, ("notes", "note", "on", "about", "for"))
        return "notes", notes(topic)

    program = python_program(lowered)
    if program:
        return "python program", program

    topic = _extract_topic(lowered, ("content", "document", "doc", "file", "into", "on", "about", "for", "with"))
    return "document", default_document(topic)


def _extract_topic(text: str, stopwords: tuple[str, ...]) -> str:
    cleaned = re.sub(r"\.[a-z0-9]{1,5}\b", " ", text)          # drop file extensions
    cleaned = re.sub(r"[^a-z0-9\s+-]", " ", cleaned)
    words = cleaned.split()
    filtered: list[str] = []
    for word in words:
        if word in STOPWORDS or word in stopwords:
            continue
        if filtered and filtered[-1] == word:                  # collapse duplicates
            continue
        filtered.append(word)
    deduped: list[str] = []
    for word in filtered:
        if word not in deduped:
            deduped.append(word)
    topic = " ".join(deduped).strip()
    return topic or "study notes"


STOPWORDS = {
    "create", "make", "write", "a", "an", "the", "new", "file", "called", "named", "add",
    "into", "to", "in", "my", "me", "please", "jarvis", "some", "of", "and", "with",
    "python", "txt", "text", "folder", "content", "about", "for", "on", "document",
    "doc", "generate", "put", "give", "today", "todays", "s", "notes", "note",
    "study", "plan", "revision", "timetable", "schedule", "days", "day",
}
