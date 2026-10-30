import asyncio
import sys

from agent import SicosigAgent


async def main():
    agent = await SicosigAgent.create()
    if len(sys.argv) > 1:
        print(await agent.ask(' '.join(sys.argv[1:])))
        return
    await repl(agent)


async def repl(agent):
    while True:
        try:
            question = input('sicosig> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question in ('salir', 'exit', 'quit'):
            break
        if question:
            print(await agent.ask(question))


if __name__ == '__main__':
    asyncio.run(main())
