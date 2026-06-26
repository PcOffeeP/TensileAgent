"""TensileAgent configuration setup wizard.

Usage:
    python3 -m agent.setup                 # Interactive mode
    python3 -m agent.setup --api-key sk-xxx --model qwen-max   # Non-interactive
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent.config_util import (
    get_api_key,
    is_remote_configured,
    list_available_models,
    save_api_key,
    save_model,
)


# ── Colors for terminal output ──

class Colors:
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _print_banner() -> None:
    """Print the setup wizard banner."""
    print()
    print(f"{Colors.CYAN}{Colors.BOLD}╭─ TensileAgent 配置向导 ─────────────────────────╮{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}│{'':62}│{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}│  欢迎！使用此向导来配置远程决策模型。            │{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}│{'':62}│{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}╰──────────────────────────────────────────────────╯{Colors.RESET}")
    print()


def _print_success(msg: str) -> None:
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")


def _print_error(msg: str) -> None:
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")


def _print_info(msg: str) -> None:
    print(f"{Colors.YELLOW}ℹ️  {msg}{Colors.RESET}")


# ── Interactive Wizard ──

def _interactive_setup() -> None:
    """Run the interactive setup wizard."""
    _print_banner()

    # ── Step 1: API Key ──
    print(f"{Colors.BOLD}Step 1: 请输入你的百炼 API Key{Colors.RESET}")
    print(f"  (将保存在 {Colors.YELLOW}agent/.env{Colors.RESET} 文件中，不会提交到 Git)")
    existing = get_api_key()
    if existing:
        masked = existing[:6] + "*" * (len(existing) - 10) + existing[-4:]
        print(f"  当前已配置: {Colors.GREEN}{masked}{Colors.RESET}")
        key = input(f"  直接回车保留现有 Key，输入新 Key 覆盖: ").strip()
        api_key = key if key else existing
    else:
        api_key = input(f"  → {Colors.CYAN}{Colors.BOLD}").strip()
        print(f"{Colors.RESET}", end="")
        if not api_key:
            _print_error("API Key 不能为空")
            sys.exit(1)

    print()

    # ── Step 2: Test connection ──
    print(f"{Colors.BOLD}Step 2: 正在测试连接...{Colors.RESET}")
    models = list_available_models(api_key=api_key)
    if not models:
        _print_error("连接失败或无可用模型，请检查 API Key 是否正确")
        sys.exit(1)
    _print_success(f"已连接，发现 {len(models)} 个可用模型")
    print()

    # ── Step 3: Select model ──
    print(f"{Colors.BOLD}Step 3: 请选择要使用的模型{Colors.RESET}")
    print(f"  {'#':>3}  │ 模型 ID")
    print(f"  {'─'*3}──┼──{'─'*40}")
    for i, model in enumerate(models, 1):
        print(f"  {i:>3}  │ {model}")

    print()
    try:
        choice = input(f"  请输入编号 (1-{len(models)}): ").strip()
        index = int(choice) - 1
        if index < 0 or index >= len(models):
            raise ValueError
        selected_model = models[index]
    except (ValueError, IndexError):
        _print_error(f"无效选择，请输入 1-{len(models)} 之间的数字")
        sys.exit(1)
    print()

    # ── Step 4: Save ──
    print(f"{Colors.BOLD}Step 4: 保存配置...{Colors.RESET}")
    save_api_key(api_key)
    save_model(selected_model)
    print()
    _print_success("配置完成！")
    _print_info(f"API Key 已保存到 agent/.env")
    _print_info(f"当前模型: {selected_model}")
    print()
    print(f"  运行 {Colors.CYAN}python3 -m agent.run --video xxx.mp4{Colors.RESET} 开始使用")
    print(f"  或运行 {Colors.CYAN}python3 -m agent.web_api{Colors.RESET} 启动 Web 工作台")
    print()


# ── Non-interactive Mode ──

def _non_interactive_setup(api_key: str, model: str) -> None:
    """Run setup with provided arguments."""
    save_api_key(api_key)
    save_model(model)
    _print_success("配置已保存")
    _print_info(f"API Key 已保存到 agent/.env")
    _print_info(f"模型: {model}")


# ── CLI Entry ──

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m agent.setup",
        description="TensileAgent 配置向导 — 配置远程决策模型的 API Key 和模型选择",
    )
    parser.add_argument("--api-key", type=str, default=None,
                        help="百炼 API Key（不传则进入交互模式）")
    parser.add_argument("--model", type=str, default=None,
                        help="模型名称，如 qwen-max（不传则进入交互模式）")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # If both api-key and model provided, run non-interactive
    if args.api_key and args.model:
        _non_interactive_setup(args.api_key, args.model)
        return

    # If only one of them provided, error
    if args.api_key or args.model:
        _print_error("--api-key 和 --model 必须同时提供")
        print("  交互模式: python3 -m agent.setup")
        print("  静默模式: python3 -m agent.setup --api-key sk-xxx --model qwen-max")
        sys.exit(1)

    # Otherwise, interactive mode
    _interactive_setup()


if __name__ == "__main__":
    main()
