// Config de commitlint. En .cjs y no en JSON porque `ignores` necesita funciones, y
// no en .js porque la imagen de wagoid/commitlint-github-action tiene "type": "module"
// en su package.json raíz: ahí un .js se carga como ESM y `module.exports` no existe.
module.exports = {
  extends: ["@commitlint/config-conventional"],

  rules: {
    "body-max-line-length": [2, "always", 200],
  },

  // Dependabot escribe el subject en sentence-case ("Bump python in /.deploy"), que
  // es justo lo que `subject-case` de config-conventional prohíbe. No son commits
  // humanos y su formato no es configurable desde `dependabot.yml`, así que se los
  // excluye por su firma en lugar de relajar la regla para todo el mundo: que una
  // persona no pueda escribir "Agrega X" en mayúscula sigue valiendo.
  ignores: [(mensaje) => /^Signed-off-by: dependabot\[bot\]/m.test(mensaje)],
};
