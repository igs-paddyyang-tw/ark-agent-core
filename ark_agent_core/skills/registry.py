"""SkillRegistry：技能註冊、自動發現與呼叫。"""

import importlib
import pkgutil
from pathlib import Path
from typing import Type

from ark_agent_core.skills.base import BaseSkill, SkillResult


class SkillRegistry:
    """管理所有已註冊的 Skill 實例。"""

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """註冊一個 Skill 實例。"""
        if skill.skill_id in self._skills:
            raise ValueError(f"Skill already registered: {skill.skill_id}")
        self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> BaseSkill | None:
        """根據 skill_id 取得 Skill 實例。"""
        return self._skills.get(skill_id)

    def list_skills(self) -> list[dict]:
        """列出所有已註冊的 Skill。"""
        return [s.to_dict() for s in self._skills.values()]

    async def invoke(self, skill_id: str, params: dict) -> SkillResult:
        """呼叫指定 Skill。"""
        skill = self._skills.get(skill_id)
        if skill is None:
            return SkillResult(success=False, error=f"Skill not found: {skill_id}")

        if not skill.validate_params(params):
            return SkillResult(success=False, error=f"Invalid params for skill: {skill_id}")

        try:
            return await skill.execute(params)
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def auto_discover(self, package_path: str) -> int:
        """自動掃描指定 package 下的所有模組，找到 BaseSkill 子類別並註冊。

        Args:
            package_path: 套件的 dotted path，例如 "ark_agent_core.skills.builtin"

        Returns:
            新註冊的 Skill 數量。
        """
        count = 0
        try:
            package = importlib.import_module(package_path)
        except ModuleNotFoundError:
            return 0

        package_dir = Path(package.__file__).parent if package.__file__ else None
        if package_dir is None:
            return 0

        for _importer, module_name, _is_pkg in pkgutil.iter_modules([str(package_dir)]):
            module = importlib.import_module(f"{package_path}.{module_name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                    and hasattr(attr, "skill_id")
                ):
                    try:
                        instance = attr()
                        self.register(instance)
                        count += 1
                    except Exception:
                        pass

        return count
