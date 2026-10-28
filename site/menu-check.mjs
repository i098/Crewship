import assert from "node:assert/strict";

// Run with the page adapter from chrome-devtools-axi run.
export async function checkMenu(page, origin) {
  await page.open(origin);
  await page.eval(() => {
    localStorage.removeItem("harbor-settings");
    localStorage.removeItem("harbor-sound");
  });
  await page.open(origin);
  await page.wait("#explore:not([disabled])");
  const image = () => page.eval(() => document.querySelector("canvas").toDataURL());
  const focus = () => page.eval(() => document.activeElement.id || document.activeElement.textContent);
  const choose = (id, value) => page.eval(`() => {
    const control = document.getElementById(${JSON.stringify(id)});
    control.value = ${JSON.stringify(value)};
    control.dispatchEvent(new Event("change", { bubbles: true }));
  }`);
  const initial = await image();
  await page.wait(300);
  assert.equal(await image(), initial, "The start view must stay still");
  assert.equal(await page.eval(() => performance.getEntriesByType("resource").some(e => e.name.includes("/audio/"))), false);
  assert.equal(await focus(), "explore");
  await page.press("Escape");
  await page.wait("#menu[open]");
  assert.equal(await focus(), "explore");
  await page.press("Tab");
  assert.equal(await focus(), "GitHub");
  await page.press("Tab");
  assert.equal(await focus(), "About");
  await page.press("Tab");
  assert.equal(await focus(), "Docs");
  await page.press("Tab");
  assert.equal(await focus(), "settings-open");
  await page.press("Enter");
  for (const value of ["low", "high", "auto"]) {
    await choose("graphics", value);
    assert.equal(await page.eval(() => JSON.parse(localStorage.getItem("harbor-settings")).graphics), value);
  }
  for (const value of ["full", "system", "reduce"]) {
    await choose("motion", value);
    assert.equal(await page.eval(() => JSON.parse(localStorage.getItem("harbor-settings")).motion), value);
  }
  await choose("graphics", "low");
  await page.click("#sound-choice");
  assert.equal(await page.eval(() => localStorage.getItem("harbor-sound")), "off");
  await page.press("Escape");
  assert.equal(await focus(), "settings-open");
  await page.open(origin);
  await page.wait("#explore:not([disabled])");
  await page.click("#settings-open");
  assert.deepEqual(await page.eval(() => [document.querySelector("#graphics").value, document.querySelector("#motion").value, document.querySelector("#sound-choice").checked]), ["low", "reduce", false]);
  await page.click("summary");
  assert.equal(await page.eval(() => document.querySelector("details").open), true);
  await page.press("Escape");
  await page.click("#explore");
  assert.equal(await focus(), "stage");
  await page.wait(500);
  const reduced = await image();
  await page.wait(300);
  assert.equal(await image(), reduced, "Reduced motion must stop idle animation");
  await page.eval(() => document.querySelector("#stage").dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW", key: "w", bubbles: true })));
  await page.click("#menu-open");
  await page.click("#explore");
  await page.wait(500);
  const stopped = await image();
  await page.wait(300);
  assert.equal(await image(), stopped, "Opening the menu must release held movement");
  await page.press("m");
  assert.equal(await page.eval(() => document.querySelector("#stage").classList.contains("mapping")), true);
  await page.press("Escape");
  assert.equal(await page.eval(() => document.querySelector("#menu").open), false);
  await page.press("Escape");
  assert.equal(await page.eval(() => document.querySelector("#menu").open), true);
  await page.click("#settings-open");
  await page.click("#settings-reset");
  assert.deepEqual(await page.eval(() => [document.querySelector("#graphics").value, document.querySelector("#motion").value, document.querySelector("#sound-choice").checked]), ["auto", "system", true]);
  await page.press("Escape");
  await page.click("#explore");
  await page.click("#menu-open");
  assert.equal(await page.eval(() => document.querySelector("#menu").open), true);
  await page.click("#settings-open");
  await page.eval(() => {
    const setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "harbor-settings" && JSON.parse(value).graphics === "high") throw new DOMException("Full", "QuotaExceededError");
      return setItem.call(this, key, value);
    };
  });
  await choose("graphics", "high");
  assert.match(await page.eval(() => document.querySelector("#save-status").textContent), /cannot be saved/);
  await choose("graphics", "low");
  assert.equal(await page.eval(() => document.querySelector("#save-status").textContent), "");
  assert.equal(await page.eval(() => JSON.parse(localStorage.getItem("harbor-settings")).graphics), "low");
  await page.press("Escape");
  await page.click("#menu a[href='/about']");
  assert.equal(await page.eval(() => location.pathname), "/about");
  await page.open(origin);
  await page.wait("#explore:not([disabled])");
  await page.click("#menu a[href='https://github.com/i098/Crewship']");
  assert.equal(await page.eval(() => location.href.split(/[?#]/)[0]), "https://github.com/i098/Crewship");
  await page.open(origin);
  await page.wait("#explore:not([disabled])");
  return "Menu, all preferences, reload, motion, Escape, focus, links, and blocked writes passed";
}
