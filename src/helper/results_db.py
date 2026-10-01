"""SQLite store for experiment runs: parameters, outcome and route details.

One row in ``runs`` per execution (everything needed to reproduce it plus the
headline results) and one row in ``routes`` per route of the final solution.
Column generation runs also fill ``cg_iterations`` (one row per iteration:
bounds, duals, pricing outcome and timings) and ``cg_columns`` (one row per
generated column: origin, reduced cost, whether it was ever used).
``log_path`` points at the full log file.

The database location can be overridden with the SBR_RESULTS_DB env variable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from helper import telemetry

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "results" / "results.db"
MAX_DIFF_CHARS = 1_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at                TEXT NOT NULL,
    method                    TEXT NOT NULL,
    status                    TEXT NOT NULL,
    error                     TEXT,

    -- problem parameters
    school_id                 INTEGER,
    data_source               TEXT,
    number_of_vehicles        INTEGER,
    capacity_of_vehicle       INTEGER,
    max_travel_distance       REAL,
    allowed_walking_distance  REAL,
    n_students                INTEGER,
    n_stops                   INTEGER,

    -- algorithm parameters (time limits, iteration caps, tolerances, ...)
    params_json               TEXT,

    -- results
    total_walking_distance    REAL,
    total_route_distance      REAL,
    n_routes                  INTEGER,
    wall_seconds              REAL,
    cpu_seconds               REAL,

    -- reproducibility
    git_commit                TEXT,
    git_dirty                 INTEGER,
    git_diff                  TEXT,
    python_version            TEXT,
    gurobi_version            TEXT,
    platform                  TEXT,
    data_files_json           TEXT,

    -- where the detail lives
    log_path                  TEXT
);

CREATE TABLE IF NOT EXISTS routes (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    route_idx                 INTEGER NOT NULL,
    stop_ids_json             TEXT NOT NULL,
    served_students_json      TEXT NOT NULL,
    pickup_map_json           TEXT,
    walking_distance          REAL,
    route_distance            REAL
);

CREATE INDEX IF NOT EXISTS idx_routes_run ON routes(run_id);

-- One row per column generation iteration (root and branch-and-price nodes).
CREATE TABLE IF NOT EXISTS cg_iterations (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq                       INTEGER NOT NULL,   -- global order within the run
    phase                     TEXT,               -- root | branch_and_price
    node_id                   INTEGER,
    depth                     INTEGER,
    iteration                 INTEGER,            -- iteration within this CG call
    wall_s                    REAL,               -- since run start
    cpu_s                     REAL,
    rmp_obj                   REAL,
    rmp_time                  REAL,
    n_columns                 INTEGER,
    n_fractional              INTEGER,
    is_integer                INTEGER,
    dummy_lambda              REAL,
    pricing_level             TEXT,               -- heuristic | heuristic+exact | exact
    heuristic_time            REAL,
    heuristic_success         INTEGER,
    best_rc_heuristic         REAL,
    exact_time                REAL,
    exact_status              TEXT,
    best_rc_exact             REAL,               -- first improving column (BestObjStop)
    n_added                   INTEGER,
    certified                 INTEGER,            -- exact pricing proved no column
    lagrangian_lb             REAL,               -- valid lower bound when certified
    mu                        REAL,
    pi_json                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_cg_iterations_run ON cg_iterations(run_id);

-- One row per generated column.
CREATE TABLE IF NOT EXISTS cg_columns (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    col_id                    INTEGER NOT NULL,
    created_iteration         INTEGER,
    phase                     TEXT,
    node_id                   INTEGER,
    source                    TEXT,  -- dummy | init_single | greedy_* | seed_* | extend_active | exact
    reduced_cost              REAL,  -- at creation
    walking_distance          REAL,
    route_distance            REAL,
    n_students                INTEGER,
    stop_ids_json             TEXT,
    served_students_json      TEXT,
    max_lambda                REAL,  -- largest lambda ever reached in any RMP
    in_final                  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cg_columns_run ON cg_columns(run_id);
"""

ITERATION_FIELDS = (
    "phase", "node_id", "depth", "iteration", "wall_s", "cpu_s", "rmp_obj",
    "rmp_time", "n_columns", "n_fractional", "is_integer", "dummy_lambda",
    "pricing_level", "heuristic_time", "heuristic_success", "best_rc_heuristic",
    "exact_time", "exact_status", "best_rc_exact", "n_added", "certified",
    "lagrangian_lb", "mu",
)


def _db_path() -> Path:
    return Path(os.environ.get("SBR_RESULTS_DB", DEFAULT_DB_PATH))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _file_info(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        p = REPO_ROOT / path
    if not p.exists():
        return {"path": path, "sha256": None}
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"path": path, "sha256": digest, "bytes": p.stat().st_size}


def _gurobi_version() -> str | None:
    try:
        import gurobipy

        return ".".join(str(v) for v in gurobipy.gurobi.version())
    except Exception:
        return None


def _data_files() -> list[dict]:
    try:
        from config import BUS_FILE, SCHOOL_FILE, STUDENT_FILE

        return [_file_info(f) for f in (STUDENT_FILE, BUS_FILE, SCHOOL_FILE)]
    except Exception:
        return []


def _log_path(logger: logging.Logger | None) -> str | None:
    if logger is None:
        return None
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler):
            return str(Path(h.baseFilename).resolve())
    return None


class RunRecorder:
    """Context manager that stores one run (and its routes) in the database.

    Usage:
        with RunRecorder("column_generation", problem_model, params, logger) as rec:
            routes = solve(...)
            rec.set_result(routes)

    The run is saved on exit even if the body raises (status "error"), so a
    crashed or infeasible experiment still leaves a reproducible record.
    CPU time is the process CPU time (all threads, e.g. Gurobi's) spent inside
    the block; wall time is the elapsed time.
    """

    def __init__(self, method: str, problem_model, params: dict | None = None,
                 logger: logging.Logger | None = None,
                 trace: bool = True, store_duals: bool = True):
        self.method = method
        self.problem_model = problem_model
        self.params = params or {}
        self.logger = logger
        self.routes: list = []
        self.status: str | None = None
        # trace=False disables the per-iteration / per-column collection
        # entirely (the algorithm then talks to a no-op collector).
        self.trace = trace
        self.store_duals = store_duals
        self.telemetry: telemetry.Telemetry | None = None

    def set_result(self, routes, status: str | None = None) -> None:
        """Record the final routes. Dummy (artificial) routes are never stored."""
        self.routes = [r for r in (routes or []) if not getattr(r, "is_dummy", False)]
        self.status = status or ("success" if self.routes else "no_solution")
        if self.telemetry is not None:
            self.telemetry.mark_final(self.routes)

    def __enter__(self) -> "RunRecorder":
        if self.trace:
            self.telemetry = telemetry.Telemetry(store_duals=self.store_duals)
            telemetry.activate(self.telemetry)
        self._wall0 = time.perf_counter()
        self._cpu0 = time.process_time()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Stop the clock first: everything below (git calls, serialisation,
        # database writes) is excluded from the measured run time.
        wall = time.perf_counter() - self._wall0
        cpu = time.process_time() - self._cpu0
        telemetry.deactivate()
        error = None
        if exc_type is not None:
            self.status, error = "error", f"{exc_type.__name__}: {exc}"
        try:
            run_id = self._save(wall, cpu, error)
            if self.logger:
                self.logger.info(f"Run saved to {_db_path()} (run id {run_id}).")
        except Exception as save_err:  # never let bookkeeping hide the real result
            msg = f"Could not save run to database: {save_err}"
            if self.logger:
                self.logger.error(msg)
            else:
                print(msg, file=sys.stderr)
        return False  # re-raise the original exception, if any

    def _save(self, wall: float, cpu: float, error: str | None) -> int:
        pm = self.problem_model
        diff = _git("diff", "HEAD")
        status_out = _git("status", "--porcelain")
        dirty = None if status_out is None else int(bool(status_out.strip()))
        if diff and len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + "\n... [truncated]"

        total_walk = sum(r.total_walking_distance for r in self.routes) if self.routes else None
        total_dist = sum(r.total_distance for r in self.routes) if self.routes else None

        conn = _connect()
        try:
            with conn:
                cur = conn.execute(
                    """INSERT INTO runs (
                        created_at, method, status, error,
                        school_id, data_source, number_of_vehicles, capacity_of_vehicle,
                        max_travel_distance, allowed_walking_distance, n_students, n_stops,
                        params_json, total_walking_distance, total_route_distance, n_routes,
                        wall_seconds, cpu_seconds, git_commit, git_dirty, git_diff,
                        python_version, gurobi_version, platform, data_files_json, log_path
                    ) VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?,?,?)""",
                    (
                        datetime.now().isoformat(timespec="seconds"),
                        self.method,
                        self.status or "no_solution",
                        error,
                        pm.school_id,
                        getattr(getattr(pm, "distance_metric", None), "value", None),
                        pm.number_of_vehicles,
                        pm.capacity_of_vehicle,
                        pm.max_travel_distance,
                        pm.allowed_walking_dist,
                        len(pm.students),
                        len(pm.all_stops),
                        json.dumps(self.params, sort_keys=True, default=str),
                        total_walk,
                        total_dist,
                        len(self.routes),
                        wall,
                        cpu,
                        (_git("rev-parse", "HEAD") or "").strip() or None,
                        dirty,
                        diff or None,
                        sys.version.split()[0],
                        _gurobi_version(),
                        platform.platform(),
                        json.dumps(_data_files()),
                        _log_path(self.logger),
                    ),
                )
                run_id = cur.lastrowid
                conn.executemany(
                    """INSERT INTO routes (
                        run_id, route_idx, stop_ids_json, served_students_json,
                        pickup_map_json, walking_distance, route_distance
                    ) VALUES (?,?,?,?,?,?,?)""",
                    [
                        (
                            run_id,
                            idx,
                            json.dumps([s.second_id for s in r.stops]),
                            json.dumps(sorted(r.served_students)),
                            json.dumps(
                                {str(k): v for k, v in (r.pickup_map or {}).items()}
                            ),
                            r.total_walking_distance,
                            r.total_distance,
                        )
                        for idx, r in enumerate(self.routes)
                    ],
                )
                if self.telemetry is not None:
                    self._save_trace(conn, run_id, self.telemetry)
            return run_id
        finally:
            conn.close()

    @staticmethod
    def _save_trace(conn: sqlite3.Connection, run_id: int, tel) -> None:
        def as_int(v):
            return None if v is None else int(v)

        conn.executemany(
            f"""INSERT INTO cg_iterations (run_id, seq, {", ".join(ITERATION_FIELDS)}, pi_json)
                VALUES (?, ?, {", ".join("?" for _ in ITERATION_FIELDS)}, ?)""",
            [
                (
                    run_id,
                    seq,
                    *(
                        as_int(row.get(f)) if f in ("is_integer", "heuristic_success", "certified")
                        else row.get(f)
                        for f in ITERATION_FIELDS
                    ),
                    None if row.get("pi") is None
                    else json.dumps({str(k): v for k, v in row["pi"].items()}),
                )
                for seq, row in enumerate(tel.iterations)
            ],
        )
        conn.executemany(
            """INSERT INTO cg_columns (
                run_id, col_id, created_iteration, phase, node_id, source,
                reduced_cost, walking_distance, route_distance, n_students,
                stop_ids_json, served_students_json, max_lambda, in_final
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id,
                    col_id,
                    c["iteration"],
                    c["phase"],
                    c["node_id"],
                    c["source"],
                    c["reduced_cost"],
                    c["route"].total_walking_distance,
                    c["route"].total_distance,
                    len(c["route"].served_students),
                    json.dumps([s.second_id for s in c["route"].stops]),
                    json.dumps(sorted(c["route"].served_students)),
                    c["max_lambda"],
                    int(c["in_final"]),
                )
                for col_id, c in tel.columns.items()
            ],
        )
