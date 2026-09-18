"""Alembic upgrade/downgrade and correlation uniqueness for Phase 1."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


class Phase1MigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_and_unique_correlation(self):
        handle = tempfile.NamedTemporaryFile(prefix='qa_alembic_test_', suffix='.db', delete=False)
        handle.close()
        db_path = handle.name
        url = f'sqlite:///{db_path}'
        env = os.environ.copy()
        env['DATABASE_URL'] = url
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')

        venv_python = ROOT / '.venv' / 'bin' / 'python'
        python = str(venv_python if venv_python.exists() else Path(sys.executable))

        def alembic_cmd(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [python, '-m', 'alembic', *args],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        try:
            up = alembic_cmd('upgrade', 'head')
            self.assertEqual(up.returncode, 0, up.stdout + up.stderr)

            engine = create_engine(url)
            inspector = inspect(engine)
            columns = {col['name'] for col in inspector.get_columns('test_runs')}
            self.assertTrue({'ci_provider', 'ci_repository', 'ci_run_id'}.issubset(columns))

            indexes = inspector.get_indexes('test_runs')
            correlation = [idx for idx in indexes if idx['name'] == 'ix_test_runs_ci_correlation']
            self.assertEqual(len(correlation), 1)
            self.assertFalse(correlation[0].get('unique'))

            self.assertIn('triage_results', inspector.get_table_names())
            unique = inspector.get_unique_constraints('triage_results')
            named = [item for item in unique if item['name'] == 'uq_triage_results_correlation']
            if named:
                self.assertEqual(set(named[0]['column_names']), {'provider', 'repository', 'run_id'})
            else:
                unique_indexes = [idx for idx in inspector.get_indexes('triage_results') if idx.get('unique')]
                self.assertTrue(
                    any(set(idx.get('column_names') or []) == {'provider', 'repository', 'run_id'} for idx in unique_indexes),
                    f'expected unique correlation; unique={unique} indexes={inspector.get_indexes("triage_results")}',
                )

            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO triage_results (
                            provider, repository, run_id, triage_state, created_at, updated_at
                        ) VALUES ('github-actions', 'org/repo', '1', 'ANALYZING', '2026-01-01', '2026-01-01')
                        """
                    )
                )
            with engine.begin() as conn:
                with self.assertRaises(Exception):
                    conn.execute(
                        text(
                            """
                            INSERT INTO triage_results (
                                provider, repository, run_id, triage_state, created_at, updated_at
                            ) VALUES ('github-actions', 'org/repo', '1', 'COMPLETED', '2026-01-01', '2026-01-01')
                            """
                        )
                    )

            current = alembic_cmd('current')
            self.assertIn('c3d4e5f6a7b8', current.stdout + current.stderr)

            down = alembic_cmd('downgrade', 'b2c3d4e5f6a7')
            self.assertEqual(down.returncode, 0, down.stdout + down.stderr)

            inspector = inspect(engine)
            self.assertNotIn('triage_results', inspector.get_table_names())
            columns = {col['name'] for col in inspector.get_columns('test_runs')}
            self.assertFalse({'ci_provider', 'ci_repository', 'ci_run_id'} & columns)

            up_again = alembic_cmd('upgrade', 'head')
            self.assertEqual(up_again.returncode, 0, up_again.stdout + up_again.stderr)
            engine.dispose()
        finally:
            os.unlink(db_path)


if __name__ == '__main__':
    unittest.main()
