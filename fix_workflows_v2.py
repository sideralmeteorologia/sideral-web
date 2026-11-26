#!/usr/bin/env python3
import os
import re
from pathlib import Path

WORKFLOW_DIR = Path("c:/Users/bryan/Downloads/BREAKOUT/sideral-web/.github/workflows")

# Mapping of workflow patterns to their correct restore target directories
WORKFLOW_FAMILIES = {
    "cbr-wrf.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf-ecmwf.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf-gfs.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf-icon.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf2-ecmwf.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf2-gfs.yml": "cbr_restart_input",
    "cbr-wrf-4km-wrf2-icon.yml": "cbr_restart_input",

    "cim-wrf-5km.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf-ecmwf.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf-gfs.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf-icon.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf2-ecmwf.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf2-gfs.yml": "cim4_restart_input",
    "cim-wrf-5km-wrf2-icon.yml": "cim4_restart_input",

    "cim-wrf-8km.yml": None,
    "cim-wrf-8km-wrf-ecmwf.yml": None,
    "cim-wrf-8km-wrf-gfs.yml": None,
    "cim-wrf-8km-wrf-icon.yml": None,

    "metbr-wrf.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf-ecmwf.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf-gfs.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf-icon.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf2-ecmwf.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf2-gfs.yml": "metbr_restart_input",
    "metbr-wrf-4km-wrf2-icon.yml": "metbr_restart_input",

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

    "tarc-wrf.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf-ecmwf.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf-gfs.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf-icon.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf2-ecmwf.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf2-gfs.yml": "tarc_restart_input",
    "tarc-wrf-3km-wrf2-icon.yml": "tarc_restart_input",
}

def fix_workflow(filepath: Path, restore_target: str | None) -> tuple[int, int]:
    content = filepath.read_text(encoding='utf-8')
    original_content = content

    restore_changes = 0
    duplicate_removals = 0

    # 1. Fix WRF_ARTIFACT_RESTORE_TO
    if restore_target:
        # Padrão original: WRF_ARTIFACT_RESTORE_TO: '.'
        pattern = r"WRF_ARTIFACT_RESTORE_TO:\s*['\"]\.(['\"])"
        # Correção para: WRF_ARTIFACT_RESTORE_TO: 'target'
        replacement = f"WRF_ARTIFACT_RESTORE_TO: '{restore_target}'"

        # Faz a substituição garantindo que a aspa de fechamento seja tratada
        new_content = re.sub(pattern, replacement, content)
        restore_changes = len(re.findall(pattern, content))
        content = new_content

    # 2. Fix timeout
    content = re.sub(r'timeout-minutes:\s*\d+', 'timeout-minutes: 480', content)

    # 3. Remove duplicate unpack-downloads IF 'Register WRF artifact restore target' exists
    if "Register WRF artifact restore target" in content:
        # Remove apenas o bloco unpack-downloads dentro de "Restore WRF artifacts after checkout"
        # Mantendo o nome do passo para evitar quebra de referência
        restore_step_pattern = re.compile(
            r'(- name: Restore WRF artifacts after checkout.*?run: \|.*?python3.*?unpack-downloads.*?\n.*?fi)',
            re.DOTALL
        )

        def replace_restore_step(match):
            step = match.group(1)
            # Substitui por um passo que não faz nada
            return step.split('run:')[0] + "run: echo 'Artifacts already restored in Register step'"

        if restore_step_pattern.search(content):
            content = restore_step_pattern.sub(replace_restore_step, content)
            duplicate_removals = 1 # Simplified count

    if content != original_content:
        filepath.write_text(content, encoding='utf-8')
        print(f"Fixed: {filepath.name} - {restore_changes} restore targets, {duplicate_removals} duplicate steps")
    else:
        print(f"No changes needed: {filepath.name}")

    return restore_changes, duplicate_removals

def main():
    for workflow_file, restore_target in WORKFLOW_FAMILIES.items():
        filepath = WORKFLOW_DIR / workflow_file
        if filepath.exists():
            fix_workflow(filepath, restore_target)
        else:
            print(f"NOT FOUND: {workflow_file}")

if __name__ == "__main__":
    main()
