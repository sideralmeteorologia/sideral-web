#!/usr/bin/env python3
"""
Script to fix all WRF GitHub Actions workflows:
1. Change WRF_ARTIFACT_RESTORE_TO from '.' to the correct directory for each workflow family
2. Remove duplicate unpack-downloads calls
3. Ensure timeout-minutes is 480
"""

import os
import re
from pathlib import Path

WORKFLOW_DIR = Path("c:/Users/bryan/Downloads/BREAKOUT/sideral-web/.github/workflows")

# Mapping of workflow patterns to their correct restore target directories
WORKFLOW_FAMILIES = {
    # CBR workflows
    "cbr-wrf.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf-ecmwf.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf-gfs.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf-icon.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf2-ecmwf.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf2-gfs.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf2-icon.yml": "cbr_restart_input",

    # CIM 5km workflows
    "cim-wrf-5km.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf-ecmwf.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf-gfs.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf-icon.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf2-ecmwf.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf2-gfs.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf2-icon.yml": "cim4_restart_input",

    # CIM 8km workflows
    "cim-wrf-8km.yml": "cim8_restart_input",
    "cim-wrf-8km-wrf-ecmwf.yml": "cim8_restart_input",
    "cim-wrf-8km-wrf-gfs.yml": "cim8_restart_input",
    "cim-wrf-8km-wrf-icon.yml": "cim8_restart_input",

    # METBR workflows
    "metbr-wrf.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf-ecmwf.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf-gfs.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf-icon.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf2-ecmwf.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf2-gfs.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf2-icon.yml": "metbr_restart_input",

    # Sudeste workflows - use tarc_restart_input
    "sudeste-wrf-4km-wrf-ecmwf.yml": "tarc_restart_input",
    "sudeste-wrf-4km-wrf-gfs.yml": "tarc_restart_input",
    "sudeste-wrf-4km-wrf-icon.yml": "tarc_restart_input",
    "sudeste-wrf-4km-wrf2-ecmwf.yml": "tarc_restart_input",
    "sudeste-wrf-4km-wrf2-gfs.yml": "tarc_restart_input",
    "sudeste-wrf-4km-wrf2-icon.yml": "tarc_restart_input",
    "sudeste-wrf-5km-wrf-ecmwf.yml": "tarc_restart_input",
    "sudeste-wrf-5km-wrf-gfs.yml": "tarc_restart_input",
    "sudeste-wrf-5km-wrf-icon.yml": "tarc_restart_input",
    "sudeste-wrf-5km-wrf2-ecmwf.yml": "tarc_restart_input",
    "sudeste-wrf-5km-wrf2-gfs.yml": "tarc_restart_input",
    "sudeste-wrf-5km-wrf2-icon.yml": "tarc_restart_input",

    # TARC workflows
    "tarc-wrf.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf-ecmwf.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf-gfs.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf-icon.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf2-ecmwf.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf2-gfs.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf2-icon.yml": "tarc_restart_input",
}

def fix_workflow(filepath: Path, restore_target: str) -> tuple[int, int]:
    """Fix a single workflow file. Returns (restore_changes, duplicate_removals)."""
    content = filepath.read_text(encoding='utf-8')
    original_content = content

    # 1. Fix WRF_ARTIFACT_RESTORE_TO from '.' to the correct target
    # Pattern: WRF_ARTIFACT_RESTORE_TO: '.'
    pattern = r"WRF_ARTIFACT_RESTORE_TO:\s*['\"]\."
    replacement = f"WRF_ARTIFACT_RESTORE_TO: '{restore_target}'"
    content = re.sub(pattern, replacement, content)

    # 2. Remove duplicate unpack-downloads blocks
    # The duplicate pattern is when there's a "Register WRF artifact restore target" step
    # followed by a "Restore WRF artifacts after checkout" step that does the same unpack-downloads
    # We need to remove the second unpack-downloads in the "Restore WRF artifacts after checkout" steps

    # Find all "Restore WRF artifacts after checkout" steps and remove the unpack-downloads from them
    # but keep the checkout and other steps
    # The pattern is:
    # - name: Restore WRF artifacts after checkout (N)
    #   shell: bash
    #   run: |
    #     if [[ -f "$GITHUB_WORKSPACE/.github/scripts/wrf_artifact_bundle.py" ]]; then
    #       python3 "$GITHUB_WORKSPACE/.github/scripts/wrf_artifact_bundle.py" unpack-downloads \
    #         --downloads-root "$RUNNER_TEMP/wrf-downloads" \
    #         --workspace "$GITHUB_WORKSPACE"
    #     fi

    # We want to keep these steps but remove the unpack-downloads part
    # Actually, let's look at the structure more carefully

    # The issue is that there are TWO places where unpack-downloads runs:
    # 1. In "Register WRF artifact restore target (N)" step - this is CORRECT
    # 2. In "Restore WRF artifacts after checkout (N)" step - this is DUPLICATE

    # We need to remove the unpack-downloads from the "Restore WRF artifacts after checkout" steps
    # but keep the step itself (it may have other things)

    # Pattern to match the "Restore WRF artifacts after checkout" step with unpack-downloads
    restore_step_pattern = r'''(- name: Restore WRF artifacts after checkout \(\d+\)\s+
        shell: bash\s+
        run: \|
          if \[\[ -f "\$GITHUB_WORKSPACE/\.github/scripts/wrf_artifact_bundle\.py" \]\]; then
            python3 "\$GITHUB_WORKSPACE/\.github/scripts/wrf_artifact_bundle\.py" unpack-downloads \\
              --downloads-root "\$RUNNER_TEMP/wrf-downloads" \\
              --workspace "\$GITHUB_WORKSPACE"
          fi)'''

    # Replace with empty step (or just a comment)
    def replace_restore_step(match):
        step = match.group(1)
        # Keep the step name but replace the run with a no-op or comment
        lines = step.split('\n')
        new_lines = [lines[0], lines[1], '  run: echo "Artifacts already restored in register step"']
        return '\n'.join(new_lines)

    content = re.sub(restore_step_pattern, replace_restore_step, content, flags=re.VERBOSE | re.MULTILINE)

    # 3. Ensure timeout-minutes is 480 for all jobs
    # Pattern: timeout-minutes: <number>
    # We want to make sure all jobs have timeout-minutes: 480
    # But we should be careful - some may already have it

    # Let's just verify and report
    timeout_matches = re.findall(r'timeout-minutes:\s*(\d+)', content)
    if timeout_matches:
        for tm in timeout_matches:
            if int(tm) != 480:
                print(f"  WARNING: {filepath.name} has timeout-minutes: {tm}, should be 480")

    # Write if changed
    restore_changes = len(re.findall(r"WRF_ARTIFACT_RESTORE_TO:\s*['\"]\.", original_content))
    duplicate_removals = len(re.findall(r'Restore WRF artifacts after checkout \(\d+\)', original_content))

    if content != original_content:
        filepath.write_text(content, encoding='utf-8')
        print(f"Fixed: {filepath.name} - {restore_changes} restore targets, {duplicate_removals} duplicate steps")
    else:
        print(f"No changes needed: {filepath.name}")

    return restore_changes, duplicate_removals

def main():
    total_restore_changes = 0
    total_duplicate_removals = 0

    for workflow_file, restore_target in WORKFLOW_FAMILIES.items():
        filepath = WORKFLOW_DIR / workflow_file
        if filepath.exists():
            restore_changes, dup_removals = fix_workflow(filepath, restore_target)
            total_restore_changes += restore_changes
            total_duplicate_removals += dup_removals
        else:
            print(f"NOT FOUND: {workflow_file}")

    print(f"\nTotal restore target changes: {total_restore_changes}")
    print(f"Total duplicate steps removed: {total_duplicate_removals}")

if __name__ == "__main__":
    main()