/**
 * Vehicle period form
 * ===================
 * One Google Form with three dropdowns: Customer, Vehicle number, Period.
 * Every submission updates the "Tracker" tab of this spreadsheet (one row per
 * customer + vehicle + period) and adds a line to the "Log" tab.
 *
 * The dropdown choices come from the Customers, Vehicles and Periods tabs.
 * After you change those lists, use the sheet menu
 *     Vehicle form  >  Rebuild form from the lists
 * so the form picks up the change. The form link stays the same.
 *
 * First time: in the spreadsheet open Extensions > Apps Script, paste this
 * whole file over the sample code, save, choose the function "setup" in the
 * toolbar and press Run. README.md walks through it step by step.
 */

// Names of the tabs this script creates and uses.
var TABS = {
  settings: 'Settings',
  customers: 'Customers',
  vehicles: 'Vehicles',
  periods: 'Periods',
  tracker: 'Tracker',
  log: 'Log',
};

// Titles of the three questions on the form. The submit handler finds the
// answers by these titles. If you rename one, rebuild the form afterwards.
var QUESTION = {
  customer: 'Customer',
  vehicle: 'Vehicle number',
  period: 'Period',
};

// Labels in column A of the Settings tab. Do not rename them in the sheet.
var SETTING = {
  title: 'Form title',
  description: 'Form description',
  collectEmail: 'Collect respondent email (Yes/No)',
  link: 'Form link (share this one)',
  editLink: 'Form edit link',
  lastRebuilt: 'Form last rebuilt',
  notes: 'Notes from the last rebuild',
};

var SETTING_DEFAULTS = [
  [SETTING.title, 'Vehicle period update'],
  [SETTING.description, 'Choose the customer, the vehicle and the period, then press Submit.'],
  [SETTING.collectEmail, 'No'],
  [SETTING.link, ''],
  [SETTING.editLink, ''],
  [SETTING.lastRebuilt, ''],
  [SETTING.notes, ''],
];

var TRACKER_HEADERS = ['Customer', 'Vehicle number', 'Period', 'Last updated', 'Updated by', 'Times submitted'];
var LOG_HEADERS = ['Submitted at', 'Customer', 'Vehicle number', 'Period', 'Submitted by', 'Response ID'];

// Help text put on each per-customer vehicle question, so the submit handler
// can tell which customer's vehicle list was answered.
var VEHICLE_HELP_PREFIX = 'Customer: ';

var PROP_FORM_ID = 'VEHICLE_FORM_ID';
var SUBMIT_HANDLER = 'handleFormSubmit';

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------

/** Adds the "Vehicle form" menu when the spreadsheet is opened. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Vehicle form')
    .addItem('Rebuild form from the lists', 'rebuildForm')
    .addItem('Show form link', 'showFormLink')
    .addSeparator()
    .addItem('First-time setup', 'setup')
    .addToUi();
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

/**
 * Run this once. Creates the tabs (with a few sample rows), creates the Google
 * Form, connects the form to this script and builds the questions.
 * Safe to run again: it keeps the same form and the same lists.
 */
function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureTabs_(ss);
  var form = getOrCreateForm_(ss);
  installSubmitTrigger_(form);
  rebuildForm();
  say_(ss, 'Setup finished. The form link is on the Settings tab.');
  try {
    showFormLink();
  } catch (err) {
    // Not running inside the spreadsheet window (for example from the script editor).
    Logger.log('Form link: ' + readSetting_(ss, SETTING.link));
  }
}

/**
 * Builds (or rebuilds) the form questions from the Customers, Vehicles and
 * Periods tabs. Run it after every change to those lists.
 */
function rebuildForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureTabs_(ss);
  var lists = readLists_(ss);

  var problems = [];
  if (!lists.customers.length) problems.push('the Customers tab is empty');
  if (!lists.vehicles.length) problems.push('the Vehicles tab is empty');
  if (!lists.periods.length) problems.push('the Periods tab is empty');
  if (problems.length) {
    throw new Error('Cannot build the form because ' + problems.join(' and ') + '. Fill it in and try again.');
  }

  var form = getOrCreateForm_(ss);
  form.setTitle(readSetting_(ss, SETTING.title) || 'Vehicle period update')
    .setDescription(readSetting_(ss, SETTING.description))
    .setCollectEmail(isYes_(readSetting_(ss, SETTING.collectEmail)))
    .setConfirmationMessage('Saved. The Tracker sheet has been updated.')
    .setShowLinkToRespondAgain(true)
    .setAllowResponseEdits(false)
    .setLimitOneResponsePerUser(false)
    .setProgressBar(false);

  // Start from a blank form. Old answers stay in the form's own Responses view.
  form.getItems().forEach(function (item) { form.deleteItem(item); });

  // If any vehicle names a customer, each customer gets their own vehicle list.
  var perCustomer = lists.vehicles.some(function (v) { return v.customer !== ''; });
  var notes = perCustomer ? buildPerCustomer_(form, lists) : buildFlat_(form, lists);

  var link = form.getPublishedUrl();
  try { link = form.shortenFormUrl(link); } catch (err) { /* keep the long link */ }
  writeSetting_(ss, SETTING.link, link);
  writeSetting_(ss, SETTING.editLink, form.getEditUrl());
  writeSetting_(ss, SETTING.lastRebuilt, Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm'));
  writeSetting_(ss, SETTING.notes, notes);
  say_(ss, 'Form rebuilt. ' + notes);
}

/** Shows the form link in a small window (from the Vehicle form menu). */
function showFormLink() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var link = readSetting_(ss, SETTING.link);
  var editLink = readSetting_(ss, SETTING.editLink);
  var ui = SpreadsheetApp.getUi();
  if (!link) {
    ui.alert('There is no form yet. Choose "First-time setup" from the Vehicle form menu.');
    return;
  }
  var html = HtmlService.createHtmlOutput(
    '<div style="font-family:sans-serif;font-size:14px;line-height:1.6;word-break:break-all">' +
    '<p><b>Form link</b> (this is the one to open or share):<br>' +
    '<a href="' + escapeHtml_(link) + '" target="_blank">' + escapeHtml_(link) + '</a></p>' +
    '<p><b>Edit link</b> (only to change colours or wording in the form itself):<br>' +
    '<a href="' + escapeHtml_(editLink) + '" target="_blank">' + escapeHtml_(editLink) + '</a></p>' +
    '</div>'
  ).setWidth(560).setHeight(230);
  ui.showModalDialog(html, 'Vehicle form');
}

/**
 * Forgets which form belongs to this sheet, so the next setup creates a new
 * one. Only needed if the form was deleted for good, or if you want to start
 * over with a fresh form. The old Tracker and Log rows are kept.
 */
function forgetForm() {
  PropertiesService.getScriptProperties().deleteProperty(PROP_FORM_ID);
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  writeSetting_(ss, SETTING.link, '');
  writeSetting_(ss, SETTING.editLink, '');
  say_(ss, 'Form forgotten. Run "First-time setup" to create a new one.');
}

// ---------------------------------------------------------------------------
// Form submit: update the Tracker and the Log
// ---------------------------------------------------------------------------

/**
 * Runs automatically every time the form is submitted (installed by setup).
 * Finds the three answers, then updates the matching Tracker row or adds one.
 */
function handleFormSubmit(e) {
  if (!e || !e.response) {
    throw new Error('handleFormSubmit runs by itself when the form is submitted; there is no need to run it by hand.');
  }
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var response = e.response;

  var customer = '';
  var period = '';
  var firstVehicle = '';
  var vehicleByCustomer = {};

  response.getItemResponses().forEach(function (itemResponse) {
    var item = itemResponse.getItem();
    var title = item.getTitle();
    var raw = itemResponse.getResponse();
    var value = String(raw === null || raw === undefined ? '' : raw).trim();
    if (!value) return;
    if (title === QUESTION.customer) {
      if (!customer) customer = value;
    } else if (title === QUESTION.period) {
      if (!period) period = value;
    } else if (title === QUESTION.vehicle) {
      var help = item.getHelpText() || '';
      if (help.indexOf(VEHICLE_HELP_PREFIX) === 0) {
        vehicleByCustomer[norm_(help.slice(VEHICLE_HELP_PREFIX.length))] = value;
      }
      if (!firstVehicle) firstVehicle = value;
    }
  });

  // In the per-customer layout, use the vehicle chosen on the selected customer's page.
  var vehicle = vehicleByCustomer[norm_(customer)] || firstVehicle;

  var email = '';
  try { email = response.getRespondentEmail() || ''; } catch (err) { email = ''; }
  var when = response.getTimestamp() || new Date();
  var responseId = response.getId();

  var lock = LockService.getScriptLock();
  lock.waitLock(30 * 1000);
  try {
    var log = ss.getSheetByName(TABS.log);
    if (alreadyLogged_(log, responseId)) return;   // the same submission delivered twice
    if (!customer || !vehicle || !period) {
      log.appendRow([when, customer, vehicle, period, email, responseId + ' (PROBLEM: an answer is missing, Tracker not updated)']);
      throw new Error('Submission ' + responseId + ' is missing an answer. Customer="' + customer + '" Vehicle="' + vehicle + '" Period="' + period + '". Rebuild the form from the lists.');
    }
    upsertTracker_(ss, customer, vehicle, period, when, email);
    log.appendRow([when, customer, vehicle, period, email, responseId]);
  } finally {
    lock.releaseLock();
  }
}

/** One row per customer + vehicle + period. Existing row: stamp it; new: add it. */
function upsertTracker_(ss, customer, vehicle, period, when, email) {
  var sheet = ss.getSheetByName(TABS.tracker);
  var lastRow = sheet.getLastRow();
  var row = 0;
  if (lastRow >= 2) {
    var keys = sheet.getRange(2, 1, lastRow - 1, 3).getDisplayValues();
    for (var i = 0; i < keys.length; i++) {
      if (norm_(keys[i][0]) === norm_(customer) &&
          norm_(keys[i][1]) === norm_(vehicle) &&
          norm_(keys[i][2]) === norm_(period)) {
        row = i + 2;
        break;
      }
    }
  }
  if (row) {
    var times = Number(sheet.getRange(row, 6).getValue()) || 0;
    sheet.getRange(row, 4, 1, 3).setValues([[when, email, times + 1]]);
  } else {
    sheet.appendRow([customer, vehicle, period, when, email, 1]);
  }
}

function alreadyLogged_(log, responseId) {
  var lastRow = log.getLastRow();
  if (lastRow < 2 || !responseId) return false;
  var ids = log.getRange(2, 6, lastRow - 1, 1).getDisplayValues();
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]).indexOf(responseId) === 0) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Building the questions
// ---------------------------------------------------------------------------

/** Three dropdowns on one page. Every vehicle is offered for every customer. */
function buildFlat_(form, lists) {
  var numbers = unique_(lists.vehicles.map(function (v) { return v.number; }));
  addDropdown_(form, QUESTION.customer, lists.customers);
  addDropdown_(form, QUESTION.vehicle, numbers);
  addDropdown_(form, QUESTION.period, lists.periods);
  return lists.customers.length + ' customers, ' + numbers.length + ' vehicles, ' + lists.periods.length +
    ' periods. Every vehicle is offered for every customer (no vehicle on the Vehicles tab names a customer).';
}

/**
 * Page 1: Customer. Picking a customer jumps to that customer's own page with
 * only their vehicles (plus vehicles whose Customer cell is blank). Every
 * customer page then jumps to the last page, Period.
 */
function buildPerCustomer_(form, lists) {
  var customerItem = form.addListItem().setTitle(QUESTION.customer).setRequired(true);

  var pages = [];
  var skipped = [];
  lists.customers.forEach(function (customer) {
    var numbers = unique_(lists.vehicles
      .filter(function (v) { return v.customer === '' || norm_(v.customer) === norm_(customer); })
      .map(function (v) { return v.number; }));
    if (!numbers.length) {
      skipped.push(customer);
      return;
    }
    var page = form.addPageBreakItem().setTitle(customer);
    form.addListItem()
      .setTitle(QUESTION.vehicle)
      .setHelpText(VEHICLE_HELP_PREFIX + customer)
      .setChoiceValues(numbers)
      .setRequired(true);
    pages.push({ customer: customer, page: page });
  });
  if (!pages.length) {
    throw new Error('No customer has a vehicle. Check the Customer column on the Vehicles tab.');
  }

  var periodPage = form.addPageBreakItem().setTitle(QUESTION.period);
  addDropdown_(form, QUESTION.period, lists.periods);

  // In Google Forms the "after this section, go to ..." rule is stored on the
  // page break that FOLLOWS the section. So for each customer page, tell the
  // next page break to jump to the Period page instead of showing the next
  // customer. The last customer page is followed by the Period page already.
  for (var i = 0; i + 1 < pages.length; i++) {
    pages[i + 1].page.setGoToPage(periodPage);
  }

  customerItem.setChoices(pages.map(function (p) {
    return customerItem.createChoice(p.customer, p.page);
  }));

  var notes = pages.length + ' customers, ' + lists.vehicles.length + ' vehicles, ' + lists.periods.length +
    ' periods. Each customer sees only their own vehicles, plus any vehicle whose Customer cell is blank.';
  if (skipped.length) {
    notes += ' Left out of the form because they have no vehicles: ' + skipped.join(', ') + '.';
  }
  return notes;
}

function addDropdown_(form, title, values) {
  return form.addListItem().setTitle(title).setChoiceValues(values).setRequired(true);
}

// ---------------------------------------------------------------------------
// Reading the lists and settings
// ---------------------------------------------------------------------------

function readLists_(ss) {
  var customerRows = rows_(ss, TABS.customers, 1);
  var vehicleRows = rows_(ss, TABS.vehicles, 2);
  var periodRows = rows_(ss, TABS.periods, 1);

  var vehicles = [];
  var seen = {};
  vehicleRows.forEach(function (r) {
    var number = r[0];
    var customer = r[1];
    if (!number) return;
    var key = norm_(number) + '\u0000' + norm_(customer);
    if (seen[key]) return;
    seen[key] = true;
    vehicles.push({ number: number, customer: customer });
  });

  // Customers tab first, then any customer named only on the Vehicles tab.
  var customers = unique_(
    customerRows.map(function (r) { return r[0]; })
      .concat(vehicles.map(function (v) { return v.customer; }))
      .filter(Boolean)
  );
  var periods = unique_(periodRows.map(function (r) { return r[0]; }).filter(Boolean));
  return { customers: customers, vehicles: vehicles, periods: periods };
}

/** Rows 2.. of a tab as trimmed text, skipping rows that are completely empty. */
function rows_(ss, tabName, numCols) {
  var sheet = ss.getSheetByName(tabName);
  if (!sheet) throw new Error('The tab "' + tabName + '" is missing. Run "First-time setup" to create it.');
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  return sheet.getRange(2, 1, lastRow - 1, numCols).getDisplayValues()
    .map(function (r) { return r.map(function (c) { return String(c).trim(); }); })
    .filter(function (r) { return r.some(function (c) { return c !== ''; }); });
}

function readSetting_(ss, name) {
  var sheet = ss.getSheetByName(TABS.settings);
  if (!sheet || sheet.getLastRow() < 2) return '';
  var rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, 2).getDisplayValues();
  for (var i = 0; i < rows.length; i++) {
    if (norm_(rows[i][0]) === norm_(name)) return String(rows[i][1]).trim();
  }
  return '';
}

function writeSetting_(ss, name, value) {
  var sheet = ss.getSheetByName(TABS.settings);
  var lastRow = sheet.getLastRow();
  var labels = lastRow >= 2 ? sheet.getRange(2, 1, lastRow - 1, 1).getDisplayValues() : [];
  for (var i = 0; i < labels.length; i++) {
    if (norm_(labels[i][0]) === norm_(name)) {
      sheet.getRange(i + 2, 2).setValue(value);
      return;
    }
  }
  sheet.appendRow([name, value]);
}

// ---------------------------------------------------------------------------
// Tabs, form and trigger
// ---------------------------------------------------------------------------

function ensureTabs_(ss) {
  var settings = ensureTab_(ss, TABS.settings, ['Setting', 'Value']);
  if (settings.getLastRow() < 2) {
    settings.getRange(2, 1, SETTING_DEFAULTS.length, 2).setValues(SETTING_DEFAULTS);
  }
  settings.setColumnWidth(1, 280);
  settings.setColumnWidth(2, 560);

  var customers = ensureTab_(ss, TABS.customers, ['Customer']);
  if (customers.getLastRow() < 2) {
    customers.getRange(2, 1, 2, 1).setValues([['Acme Ltd'], ['Brown Transport']]);
  }

  var vehicles = ensureTab_(ss, TABS.vehicles, ['Vehicle number', 'Customer (optional)']);
  vehicles.getRange('A:A').setNumberFormat('@');   // keeps numbers like 0042 as typed
  if (vehicles.getLastRow() < 2) {
    vehicles.getRange(2, 1, 4, 2).setValues([
      ['ABC 123', 'Acme Ltd'],
      ['ABC 456', 'Acme Ltd'],
      ['BT 789', 'Brown Transport'],
      ['POOL 1', ''],
    ]);
  }

  var periods = ensureTab_(ss, TABS.periods, ['Period']);
  periods.getRange('A:A').setNumberFormat('@');
  if (periods.getLastRow() < 2) {
    var months = nextMonths_(12);
    periods.getRange(2, 1, months.length, 1).setValues(months.map(function (m) { return [m]; }));
  }

  var tracker = ensureTab_(ss, TABS.tracker, TRACKER_HEADERS);
  tracker.getRange('A:C').setNumberFormat('@');
  tracker.getRange('D:D').setNumberFormat('yyyy-mm-dd hh:mm');

  var log = ensureTab_(ss, TABS.log, LOG_HEADERS);
  log.getRange('A:A').setNumberFormat('yyyy-mm-dd hh:mm:ss');
  log.getRange('B:D').setNumberFormat('@');

  // Drop the empty "Sheet1" a new spreadsheet starts with.
  var first = ss.getSheetByName('Sheet1');
  if (first && ss.getSheets().length > 1 && first.getLastRow() === 0 && first.getLastColumn() === 0) {
    ss.deleteSheet(first);
  }
}

function ensureTab_(ss, name, headers) {
  var sheet = ss.getSheetByName(name) || ss.insertSheet(name);
  var header = sheet.getRange(1, 1, 1, headers.length);
  if (!sheet.getRange(1, 1).getValue()) header.setValues([headers]);
  header.setFontWeight('bold');
  sheet.setFrozenRows(1);
  return sheet;
}

function getOrCreateForm_(ss) {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty(PROP_FORM_ID);
  if (id) {
    try {
      return FormApp.openById(id);
    } catch (err) {
      throw new Error('The form that belongs to this sheet could not be opened (' + err.message + '). ' +
        'If it is in the Drive bin, restore it. If it is gone for good, run the function "forgetForm" ' +
        'and then "setup" again.');
    }
  }
  var form = FormApp.create(readSetting_(ss, SETTING.title) || 'Vehicle period update');
  props.setProperty(PROP_FORM_ID, form.getId());
  return form;
}

function installSubmitTrigger_(form) {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === SUBMIT_HANDLER; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger(SUBMIT_HANDLER).forForm(form).onFormSubmit().create();
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function nextMonths_(count) {
  var tz = Session.getScriptTimeZone();
  var now = new Date();
  var out = [];
  for (var i = 0; i < count; i++) {
    out.push(Utilities.formatDate(new Date(now.getFullYear(), now.getMonth() + i, 1), tz, 'yyyy-MM'));
  }
  return out;
}

/** Keeps the first spelling of each value, ignoring case and spaces around it. */
function unique_(values) {
  var seen = {};
  var out = [];
  values.forEach(function (v) {
    var k = norm_(v);
    if (!k || seen[k]) return;
    seen[k] = true;
    out.push(String(v).trim());
  });
  return out;
}

function norm_(value) {
  return String(value === null || value === undefined ? '' : value).trim().toLowerCase();
}

function isYes_(value) {
  return /^(y|yes|true|1)$/i.test(String(value || '').trim());
}

function escapeHtml_(text) {
  return String(text || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function say_(ss, message) {
  Logger.log(message);
  try { ss.toast(message, 'Vehicle form', 10); } catch (err) { /* no window to show it in */ }
}
