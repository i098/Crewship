# crewship

Turn a fresh Ubuntu 24.04 or 26.04 machine into an AI-agent coding host with [Crewship](https://github.com/i098/Crewship).

```sh
npx crewship
```

`bunx crewship` and `pnpm dlx crewship` work too. The package fetches `install.sh` from the Crewship release with the same version and runs it; it bundles nothing else. Arguments go to `./ship.sh dock`. `npx crewship update` takes the newest release instead and updates an installed host ([Update](https://github.com/i098/Crewship/blob/main/docs/install.md#update)).
