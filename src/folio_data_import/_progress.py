from rich.progress import ProgressColumn, Task
from rich.text import Text

class ItemsPerSecondColumn(ProgressColumn):
    """Renders the speed in items per second."""

    def render(self, task: Task) -> Text:
        if task.speed is None:
            return Text("?", style="progress.data.speed")
        return Text(f"{task.speed:.0f}rec/s", style="progress.data.speed")

class UserStatsColumn(ProgressColumn):
    def render(self, task):
        created = task.fields.get("created", 0)
        updated = task.fields.get("updated", 0)
        failed = task.fields.get("failed", 0)
        created_string = f"Created: {created}"
        updated_string = f"Updated: {updated}"
        failed_string = f"Failed: {failed}"
        text = Text("(")
        text.append(created_string, style="green")
        text.append(" | ")
        text.append(updated_string, style="cyan")
        text.append(" | ")
        text.append(failed_string, style="red")
        text.append(")")
        return text
