"""state_rewrite: a resumable job saves its progress by rewriting the state file in place.

The job calls a handler once per item and saves its progress (items done plus handler-provided extra
values) every few items. The bug: `save` truncates the state file and writes the new state in its
place, so a save that fails or is interrupted part-way leaves a damaged file. The loader then starts
over from scratch (or refuses to start), and every item is processed again.
"""

from prgen.template import Template

VOCAB = {
    "eval": dict(pkg="evalresume", run="run_eval", handler="grade", item="case", store="ProgressFile",
                 load_fn="load_progress", save_fn="save_progress", err="ProgressError", file="progress",
                 what="runs an eval case by case and remembers which cases are done"),
    "ingest": dict(pkg="ingestor", run="ingest", handler="index", item="document", store="IngestState",
                   load_fn="load_state", save_fn="save_state", err="StateError", file="ingest-state",
                   what="indexes documents one by one and remembers which ones are done"),
    "labeling": dict(pkg="labelpass", run="label_all", handler="labeler", item="item", store="PassState",
                     load_fn="load_pass", save_fn="save_pass", err="PassStateError", file="pass",
                     what="sends items to a labeler one by one and remembers which ones are done"),
    "migration": dict(pkg="rowmover", run="migrate", handler="copy_row", item="row", store="Checkpoint",
                      load_fn="load_checkpoint", save_fn="save_checkpoint", err="CheckpointError", file="checkpoint",
                      what="copies rows one by one and remembers which ones are done"),
}

DEST = ["temp_no_cleanup", "cleanup_misses_interrupt", "system_tmp_no_cleanup", "remove_old_first", "backup_then_inplace",
        "serialize_then_inplace", "copy_over", "remove_late"]
REGRESSIONS = ["saves_only_at_end", "skip_check_missing"]


class StateRewrite(Template):
    name = "state_rewrite"
    axes = {
        "vocab": list(VOCAB),
        "format": ["json", "lines"],
        "on_corrupt": ["reset", "raise"],
        "api": ["class", "functions"],
        "cadence": ["count", "interval"],
        "runner": ["sync", "async"],
        "layout": ["split", "single"],
        "save": ["stream", "backup_first", "helper", "text"],
        "symptom": [0, 1],
    }
    structural = ["format", "on_corrupt", "api", "cadence", "runner", "layout", "save"]
    canonical = dict(vocab="eval", format="json", on_corrupt="reset", api="class", cadence="count", runner="sync",
                     layout="split", save="stream", symptom=0)
    mutant_modes = DEST + REGRESSIONS
    alternative_modes = ["named_tempfile", "rename_instead"]

    def family(self, ax):
        # Replacing a backup-first save is a different edit from making an in-place save safe; streamed,
        # text and helper saves take the same edit.
        return "save=backup_first" if ax["save"] == "backup_first" else "save=in_place"

    def package_files(self, ax):
        if ax["layout"] == "split":
            return [("__init__.py.j2", "__init__.py"), ("state.py.j2", "state.py"), ("runner.py.j2", "runner.py")]
        return [("__init__.py.j2", "__init__.py"), ("single.py.j2", "job.py")]

    def applicable_mutants(self, ax):
        # Serializing first is exactly what the text style already does, and there an interrupt can only
        # arrive before the file is opened, so missing it in the cleanup can't be observed.
        text_only = {"serialize_then_inplace", "cleanup_misses_interrupt"}
        return [m for m in self.mutant_modes if not (ax["save"] == "text" and m in text_only)]

    def bug_revealing(self, ax):
        touched = "test_kill_right_after_the_state_file_is_touched_keeps_the_last_complete_progress"
        if ax["save"] == "text":  # the state is converted before the file is opened: only a failing write hurts
            return ["test_save_that_fails_while_writing_keeps_the_last_complete_progress", touched]
        return ["test_failed_save_keeps_the_last_complete_progress", "test_killed_save_keeps_the_last_complete_progress",
                "test_save_that_fails_while_writing_keeps_the_last_complete_progress", touched]

    def mechanism_terms(self, ax):
        return ["atomic", "os.replace", "rename", "temporary file", "temp file", "write to a different file", "fsync",
                "then move", "swap"]

    def context(self, ax):
        v = dict(VOCAB[ax["vocab"]])
        cls = ax["api"] == "class"
        state_names = ([v["store"]] if cls else [v["load_fn"], v["save_fn"]]) + ([v["err"]] if ax["on_corrupt"] == "raise" else [])
        if ax["layout"] == "split":
            init_imports = [f"from .runner import {v['run']}", "from .state import " + ", ".join(sorted(state_names))]
            init_imports.sort()
        else:
            init_imports = ["from .job import " + ", ".join(sorted(state_names + [v["run"]]))]
        exports = sorted(state_names + [v["run"]])
        ext = ".json" if ax["format"] == "json" else ".txt"
        ctx = dict(ax)
        worker_names = sorted([v["run"]] + ([v["store"]] if cls else [v["load_fn"]]) + ([v["err"]] if ax["on_corrupt"] == "raise" else []))
        public_names = sorted([v["run"]] + ([v["store"]] if cls else []))
        ctx.update(
            worker_names=", ".join(worker_names), public_names=", ".join(public_names),
            v=v, pkg=v["pkg"], cls=cls, is_async=ax["runner"] == "async", ext=ext, state_file=v["file"] + ext,
            init_imports=init_imports, all_names=exports, api_names=", ".join(f"`{n}`" for n in exports),
            description="Make a resumable job's progress survive a save that fails or is interrupted part-way.",
            keywords=["checkpointing", "crash-recovery", "file-io", ax["format"]],
        )
        return ctx


TEMPLATE = StateRewrite()
