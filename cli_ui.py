import sys

BOLD = "\033[1m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def supports_color(stream=None) -> bool:
    return (stream or sys.stdout).isatty()


def style(text: str, *codes: str, stream=None) -> str:
    if not supports_color(stream):
        return text
    return "".join(codes) + text + RESET


def bold(text: str, stream=None) -> str:
    return style(text, BOLD, stream=stream)


def bold_yellow(text: str, stream=None) -> str:
    return style(text, BOLD, YELLOW, stream=stream)


def bold_red(text: str, stream=None) -> str:
    return style(text, BOLD, RED, stream=stream)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes:.0f}m{secs:02.0f}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours:.0f}h{mins:02.0f}m"


def print_progress(done: int, total: int, elapsed: float, label: str = "Progress") -> None:
    """Single updating progress-bar line with an ETA, for LLM batch loops.

    Call once per unit of work (e.g. once per chunk). The caller must print()
    a trailing newline once done == total to move past the line.
    """
    if total <= 0:
        return
    pct = 100 * done / total
    bar_width = 30
    filled = int(bar_width * done / total)
    bar = "#" * filled + "-" * (bar_width - filled)
    if done < total:
        avg = elapsed / done if done else 0
        suffix = f"ETA {format_duration(avg * (total - done))}"
    else:
        suffix = f"done in {format_duration(elapsed)}"
    line = f"  {label} [{bar}] {pct:5.1f}%  ({done}/{total})  {suffix}"
    print("\r" + line + " " * 8, end="", flush=True)


def print_action_required(heading: str, steps: list[str], width: int = 64) -> None:
    """Bold/yellow banner + numbered next-steps block for a human checkpoint.

    Each entry in `steps` may contain embedded "\\n" for wrapped continuation
    lines (indented under the number), and may embed bold()/bold_yellow() text
    for anything the caller wants to stand out (e.g. a file path or command).
    """
    bar = bold_yellow("─" * width)
    print(f"\n{bar}", flush=True)
    print(bold_yellow(f"  ACTION REQUIRED — {heading}"), flush=True)
    print(bar, flush=True)
    print(bold("\n  Next steps:"), flush=True)
    for i, step in enumerate(steps, 1):
        first, *rest = step.split("\n")
        print(f"    {i}. {first}", flush=True)
        for line in rest:
            print(f"       {line}", flush=True)
    print(f"{bar}\n", flush=True)
