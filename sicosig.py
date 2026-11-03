import asyncio
import sys

from agent import SicosigAgent


def status(msg):
    print('» %s' % msg, file=sys.stderr, flush=True)


async def main():
    status('conectando con el servidor MCP de transporte…')
    agent = await SicosigAgent.create(status=status)
    status('agente listo')
    if len(sys.argv) > 1:
        print(await agent.ask(' '.join(sys.argv[1:]), status=status))
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
            print(await agent.ask(question, status=status))


if __name__ == '__main__':
    asyncio.run(main())
