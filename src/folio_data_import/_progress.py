from rich.progress import ProgressColumn, Task
from rich.text import Text

class ItemsPerSecondColumn(ProgressColumn):
    """Renders the speed in items per second."""

    def render(self, task: Task) -> Text:
        if task.speed is None:
            return Text("?", style="progress.data.speed")
        return Text(f"{task.speed:.0f} rec/s", style="progress.data.speed")
