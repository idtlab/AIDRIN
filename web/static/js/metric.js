// Slideshow control for the histograms

// Thumbnail image controls
function currentSlide(n) {
  showSlides((slideIndex = n));
}
function showSlides(n) {
  let lightMode = localStorage.getItem("darkmode") == "null";

  let slideContainerLight = document.getElementById(
    "slideshow-container-light"
  );
  let slideContainerDark = document.getElementById("slideshow-container-dark");
  let slidesLight = slideContainerLight.querySelectorAll(".mySlides");
  let slidesDark = slideContainerDark.querySelectorAll(".mySlides");

  let dots = document.getElementsByClassName("dot");
  if (lightMode) {
    slideContainerLight.style.display = "block";
    slideContainerDark.style.display = "none";
  } else {
    slideContainerLight.style.display = "none";
    slideContainerDark.style.display = "block";
  }
  for (i = 0; i < slidesLight.length; i++) {
    slidesLight[i].style.display = "none";
    slidesLight[slideIndex - 1].style.display = "block";
    slidesDark[i].style.display = "none";
    slidesDark[slideIndex - 1].style.display = "block";
  }

  for (i = 0; i < dots.length; i++) {
    dots[i].className = dots[i].className.replace(" activeDot", "");
  }

  dots[slideIndex - 1].className += " activeDot";
}

function clearDropdown(dropdownId) {
  var dropdown = document.getElementById(dropdownId);
  dropdown.selectedIndex = 0;
}

/* Toggles Dark Mode for Histogram Plots */
const toggleSlidesColor = () => {
  const slidesLight = document.getElementById("slideshow-container-light");
  const slidesDark = document.getElementById("slideshow-container-dark");
  if (darkmode === "null") {
    slidesLight.style.display = "none";
    slidesDark.style.display = "block";
  } else {
    slidesLight.style.display = "block";
    slidesDark.style.display = "none";
  }
};

/************ Taken out of metric data download pop up *************/
function toggleVisualization(id) {
  var element = document.getElementById(id);
  var toggleArrow = document.getElementById(id + "-toggle-arrow");
  if (element.style.display === "none" || element.style.display === "") {
    element.style.display = "block";
    toggleArrow.style.transform = "rotate(180deg)"; // Rotate arrow when open
  } else {
    element.style.display = "none";
    toggleArrow.style.transform = "rotate(0deg)"; // Reset arrow when closed
  }
}

/** Error Handling: Creates a popup with error types and server response (details) */
let errorPopup;
function openErrorPopup(type, message) {
  errorPopup = document.getElementById("error-popup");
  errorPopup.classList.add("open-popup");

  errorType = document.getElementById("error-type");
  errorType.innerHTML = "Error: " + type;

  errorMessage = document.getElementById("error-message");
  errorMessage.innerHTML = message;
}
function closeErrorPopup() {
  //error popup has to be present in the DOM for the function to call already
  errorPopup.classList.remove("open-popup");
}
// Catch resource loading errors by adding an event listener to the window
window.addEventListener(
  "error",
  function (e) {
    if (
      e.target &&
      (e.target.tagName === "IMG" ||
        e.target.tagName === "SCRIPT" ||
        e.target.tagName === "LINK")
    ) {
      console.error("Resource failed to load:", e.target.src || e.target.href);
      openErrorPopup(
        "Resource Load Error",
        `Failed to load ${e.target.tagName.toLowerCase()} from: ${
          e.target.src || e.target.href
        }`
      );
    }
  },
  true
);

$(document).ready(function () {
  console.log("Feature Set");
  console.log("retrieve:", retrieveFileUrl);
  fetch(retrieveFileUrl)
    .then((response) => response.blob()) // Convert to a Blob
    .then((fileBlob) => {
      //append to form
      var formData = new FormData();
      formData.append("file", fileBlob, "filename");

      $.ajax({
        url: "/feature-set",
        type: "POST",
        data: formData,
        contentType: false,
        processData: false,
        success: function (response) {
          if (response.success) {
            // Check if either categorical or numerical features exist in the response
            if ("categorical_features" in response) {
              createDropdown(
                response.categorical_features,
                "catFeaturesDropdown"
              );
              createCheckboxContainer(
                response.categorical_features,
                "catFeaturesCheckbox1",
                "categorical features for feature relevancy"
              );
            }

            if ("numerical_features" in response) {
              createDropdown(
                response.numerical_features,
                "numFeaturesDropdownFeaRel"
              );
              createDropdown(
                response.numerical_features,
                "numFeaturesDropdownPriv"
              );
              createCheckboxContainer(
                response.numerical_features,
                "numFeaturesCheckbox1",
                "numerical features for feature relevancy"
              );
              createCheckboxContainer(
                response.numerical_features,
                "numFeaturesCheckbox2",
                "numerical features to add noise"
              );
            }

            if ("all_features" in response) {
              // Use all features for k-anonymity, l-diversity, t-closeness, and entropy risk
              createCheckboxContainer(
                response.all_features,
                "kAnonymityQIsCheckbox",
                "quasi identifiers for k-anonymity"
              );
              createCheckboxContainer(
                response.all_features,
                "lDiversityQIsCheckbox",
                "quasi identifiers for l-diversity"
              );
              createCheckboxContainer(
                response.all_features,
                "tClosenessQIsCheckbox",
                "quasi identifiers for t-closeness"
              );
              createCheckboxContainer(
                response.all_features,
                "entropyRiskQIsCheckbox",
                "quasi identifiers for entropy risk"
              );

              // Use all features for risk scoring (these can share features with other metrics)
              createCheckboxContainer(
                response.all_features,
                "catFeaturesCheckbox2",
                "quasi identifiers to measure single attribute risk score"
              );
              createCheckboxContainer(
                response.all_features,
                "catFeaturesCheckbox3",
                "quasi identifiers to measure multiple attribute risk score"
              );
              createCheckboxContainer(
                response.all_features,
                "hipaa-identifiers-checkbox",
                "HIPAA identifiers for HIPAA compliance"
              );

              // Create dropdowns for all features
              createDropdown(
                response.all_features,
                "allFeaturesDropdownRepRate"
              );
              createDropdown(
                response.all_features,
                "allFeaturesDropdownStatRate1"
              );
              createDropdown(
                response.all_features,
                "allFeaturesDropdownStatRate2"
              );
              createDropdown(
                response.all_features,
                "allFeaturesDropdownRealRep"
              );
              createDropdown(
                response.all_features,
                "all-features-dropdown-feature-relevance"
              );
              // Create checkbox containers for class imbalance
              console.log("Creating class imbalance checkboxes with features:", response.all_features);
              createDropdown(
                response.all_features,
                "all-features-dropdown-class-imbalance",
                "target features for class imbalance"
              );

              // Create checkbox container for distance metrics with custom values
              createDistanceMetricsDropdown();

              createDropdown(response.all_features, "allFeaturesDropdownMMS");
              createDropdown(response.all_features, "allFeaturesDropdownMMM");
              createDropdown(
                response.all_features,
                "allFeaturesDropdownCondDemoDis1"
              );
              createDropdown(
                response.all_features,
                "allFeaturesDropdownCondDemoDis2"
              );
              createDropdown(
                response.all_features,
                "lDiversitySensitiveDropdown"
              );
              createDropdown(
                response.all_features,
                "tClosenessSensitiveDropdown"
              );
              // Disable Target feature checkboxes
              document.querySelectorAll(".checkboxContainerIndividual").forEach(container => {
                const dropdown = container.querySelector("select");

                const updateTargetCheckbox = () => {
                    const selectedTarget = dropdown.value;
                    // Find the target checkbox
                    const targetCheckbox = container.querySelector(`input.checkbox.individual[value="${selectedTarget}"]`);
                    if (!targetCheckbox) return;
                    // Remove previous target-feature class and enable all checkboxes
                    container.querySelectorAll("input.checkbox.individual").forEach(cb => {
                      if(cb.classList.contains("target-feature")){
                        cb.classList.remove("target-feature");
                        cb.disabled = false;
                      }
                    });

                    // Uncheck, mark, and disable the target checkbox
                    targetCheckbox.checked = false;
                    targetCheckbox.classList.add("target-feature");
                    targetCheckbox.disabled = true;
                    console.log("disabling target feature");

                    // Uncheck the select-all checkbox for the group containing this target
                    const parentDiv = targetCheckbox.closest("div");
                    if (parentDiv) {
                        const selectAll = parentDiv.querySelector("input.checkbox.select-all");
                        if (selectAll) selectAll.checked = false;
                    }
                };
                // Call once on page load
                updateTargetCheckbox();
                // Call on dropdown change
                dropdown.addEventListener("change", updateTargetCheckbox);
              });


              // Initialize main metric checkbox states first
              updateMetricCheckboxState("k-anonymity");
              updateMetricCheckboxState("l-diversity");
              updateMetricCheckboxState("t-closeness");
              updateMetricCheckboxState("single attribute risk score");
              updateMetricCheckboxState("multiple attribute risk score");
              updateMetricCheckboxState("entropy risk");
              updateMetricCheckboxState("class imbalance");

              // Then initialize cross-disabling for each metric separately
              // Use setTimeout to ensure DOM is fully updated
              setTimeout(function () {
                console.log("Calling updateCrossDisable after timeout");
                updateCrossDisable();
              }, 100);
            }
          } else {
            alert("Error: " + response.message);
          }
        },
        error: function (error) {
          console.log(error);
          openErrorPopup("", error);
        },
      }).catch((error) => {
        console.error("Error fetching file:", error);
        openErrorPopup("File Retrieval", error);
      });
    });

  function createDropdown(features, dropdownId) {
    var dropdown = $("#" + dropdownId);
    dropdown.empty(); // Clear previous options

    // Add default options
    dropdown.append($('<option value="" disabled>Select a Feature</option>'));

    // Populate the dropdown with options from the response

    for (var i = 0; i < features.length && features[0] != "{"; i++) {
      dropdown.append($("<option>").text(features[i]));
    }
  }

  //generate summary statistics
  $(document).ready(function () {
    document
      .getElementById("uploadForm")
      .addEventListener("submit", function (event) {
        event.preventDefault(); // In order to prevent autoreload on submit, so that visualization data can be added.
      });

    var formData = new FormData();
    var file = "{{ url_for('core.retrieve_uploaded_file') }}";
    formData.append("file", file);

    $.ajax({
      url: "/summary-statistics",
      type: "POST",
      data: formData,
      contentType: false,
      processData: false,
      success: function (response) {
        if (response.success) {
          $("#recordsCount").text(response.records_count);
          $("#catFeatures").text(response.categorical_features);
          $("#numFeatures").text(response.numerical_features);

          // Display additional summary statistics

          var statisticsHTML =
            '<h2 style="text-align:center">Summary Statistics Table</h2><table border="1">';
          statisticsHTML += "<tr><th>Feature</th>"; // First column header

          // Get statistic types (mean, median, etc.) from the first feature key
          var firstKey = Object.keys(response.summary_statistics)[0];
          var statKeys = Object.keys(response.summary_statistics[firstKey]);

          // Create header row with stat names
          statKeys.forEach((statKey) => {
            statisticsHTML += '<td class="statName">' + statKey + "</td>";
          });
          statisticsHTML += "</tr>"; // End header row

          // Create rows for each feature (was previously a column)
          for (var key in response.summary_statistics) {
            statisticsHTML += "<tr><th><strong>" + key + "</strong></th>"; // Feature name as row header

            // Fill in statistics for this feature
            statKeys.forEach((statKey) => {
              statisticsHTML +=
                "<td>" + response.summary_statistics[key][statKey] + "</td>";
            });

            statisticsHTML += "</tr>"; // End of row
          }

          statisticsHTML += "</table>";

          statisticsHTML += "</table>";

          statisticsHTML +=
            '<br><p id="Statresult" ><strong>Number of Features:</strong> <span id="featuresCount">' +
            response.features_count +
            "</span></p>";
          statisticsHTML +=
            '<p id="Statresult"><strong>Number of Data Points:</strong> <span id="recordsCount">' +
            response.records_count +
            "</span></p>";
          statisticsHTML +=
            '<p id="Statresult"><strong>Categorical Features:</strong> <span id="catFeatures">' +
            response.categorical_features +
            "</span></p>";
          statisticsHTML +=
            '<p id="Statresult"><strong>Numerical Features:</strong> <span id="numFeatures">' +
            response.numerical_features +
            "</span></p><br>";

          $("#summaryStatistics").html(statisticsHTML);
          // Display histograms
          var histogramsContainer = $("#histogramsContainer");
          histogramsContainer.empty();
          histogramsContainer.append(
            '<br><h2 style="margin-top:0px;">Summary Statistic Plots</h2>'
          ); // Add heading for histograms

          var lightCount = 1;
          var darkCount = 1;

          var slideshow_container_light = $(
            '<div id="slideshow-container-light" class="slideshow-container">'
          );
          var slideshow_container_dark = $(
            '<div id="slideshow-container-dark" class="slideshow-container">'
          );

          for (var feature in response.histograms) {
            var isLight = feature.includes("_light");

            var base64Image = response.histograms[feature];
            var img = document.createElement("img");
            img.src = "data:image/png;base64," + base64Image;
            img.alt = feature + " Histogram";
            // add theme class to the image
            if (isLight) {
              img.classList.add("light");
            } else {
              img.classList.add("dark");
            }
            /* Image carousel wrapper*/
            let slideDiv = $('<div class="mySlides fade"></div>');
            //show the first plot by default

            slideDiv.append(img);
            if (isLight) {
              if (lightCount == 1) slideDiv.css("display", "block");
              slideshow_container_light.append(slideDiv);
              lightCount++;
            } else {
              if (darkCount == 1) slideDiv.css("display", "block");
              slideshow_container_dark.append(slideDiv);
              darkCount++;
            }
          }
          let lightMode = localStorage.getItem("darkmode") == "null";
          if (lightMode) {
            slideshow_container_light.css("display", "block");
            slideshow_container_dark.css("display", "none");
          } else {
            slideshow_container_light.css("display", "none");
            slideshow_container_dark.css("display", "block");
          }
          histogramsContainer.append(slideshow_container_light);
          histogramsContainer.append(slideshow_container_dark);
          /* dot switcher */
          var dots = $('<div class="dots"></div>');

          for (var j = 1; j < lightCount; j++) {
            let dot = $(
              '<span class="dot" onclick="currentSlide(' + j + ')"></span>'
            );
            dots.append(dot);
            //darken the first by default
            if (j == 1) {
              dot.addClass("activeDot");
            }
          }
          histogramsContainer.append(dots);
          histogramsContainer.append("</div>");
        } else {
          alert("Error: " + response.message);
        }
      },
      error: function (error) {
        console.log(error);
        openErrorPopup("", error);
      },
    });
  });

  //generate dropdown when features of the dataset are required to select
  $(document).ready(function () {
    var formData = new FormData();
    fetch(retrieveFileUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error("File not found or server error");
        }
        return response.blob();
      })
      .then((fileBlob) => {
        formData.append("file", fileBlob, "filename");
        $.ajax({
          url: "/feature-set",
          type: "POST",
          data: formData,
          contentType: false,
          processData: false,
          success: function (response) {
            if (response.success) {
              // Use all_features for correlationCheckboxContainer
              createCheckboxContainer(
                response.all_features,
                "correlationCheckboxContainer",
                "all features for data transformation"
              );
            } else {
              console.error("Error:", response.message);
              alert("Error: " + response.message);
            }
          },
          error: function (error) {
            console.error("Error fetching features:", error);
            alert("Error fetching features: " + error);
          }
        });
      })
      .catch((error) => {
        console.error("Error fetching file:", error);
        alert("Error fetching file: " + error);
      });
  });
  function createCheckboxContainer(features, tableId, nameTag) {
    var $table = $("#" + tableId);
    $table.empty(); // Clear previous content

    // Determine a responsive number of columns (1–4) based on available width.
    // This keeps multiple columns on wide screens while collapsing to fewer
    // columns on smaller viewports, avoiding horizontal scrollbars.
    var containerWidth =
      $table.closest(".checkboxContainer").width() ||
      $table.parent().width() ||
      $(window).width() ||
      800;
    var minColumnWidth = 220; // approximate width needed per column
    var columns = Math.max(
      1,
      Math.min(4, Math.floor(containerWidth / minColumnWidth))
    );

    // Return early if no features with message
    if (!features || features.length === 0 || features[0] === "{") {
      $table.append(
        $("<tr>").append(
          $("<td colspan='" + columns + "'>").text(
            "No features available for selection"
          )
        )
      );
      return;
    }
    function updateSelectAllState(tableId) {
      const checkboxes = $table.find(".checkbox.individual").not(".target-feature");
      const selectAll = document.getElementById(tableId + "-select-all");
      if (selectAll) {
        const total = checkboxes.length;
        const checked = Array.from(checkboxes).filter(cb => cb.checked).length;
        selectAll.checked = checked === total;
      }
    }
    // Create select all for all tables except single attribute risk and laplacian noise (only one feature selected)
    var selectAllId = null;
    if(nameTag!="quasi identifiers to measure single attribute risk score"&&nameTag!="numerical features to add noise"){
      //create selectAll checkbox
      var $selectAllRow = $("<tr>")
      selectAllId = tableId + "-select-all";
      var $selectAllCell = $("<td>").attr({
        colspan: columns,
      });
      var $selectAllCheckbox = $("<input>")
        .attr({
          type: "checkbox",
          class: "checkbox select-all",
          id: selectAllId,
          disabled: false,
        });
      var selectAllLabel = $("<label>")
        .attr("for", selectAllId)
        .attr("class", "material-checkbox selectAll")
        .attr("style", "display:flex;flex-direction:row;min-width:125px;align-items:center;")
        .attr("data-tooltip", "Warning: Selecting all features may significantly increase processing time.")
        .append($selectAllCheckbox)
        .append($("<span>").addClass("checkmark"))
        .append("Select All");

      $selectAllCell.append(selectAllLabel)
      $selectAllRow.append($selectAllCell);
      $table.append($selectAllRow);
    }
    for (var i = 0; i < features.length && features[0] != "{"; i++) {
      if (i % columns === 0) {
        var row = $("<tr>");
        $table.append(row);
      }

      var checkbox = $("<input>").attr({
        type: "checkbox",
        class: "checkbox individual",
        style: "margin-right:10px",
        id: tableId + "checkbox_" + i, // Generate unique ids so all buttons work
        name: nameTag, // Set the name attribute
        value: features[i],
        // Remove disabled: true - individual checkboxes should be selectable
      });
      checkbox.on("change", function () {
        toggleValueIndividual(this);
        updateSelectAllState(tableId);
      });
      var span = $("<span>").addClass("checkmark");

      var label = $("<label>")
        // .attr('class','material-checkbox')
        .attr(
          "style",
          "display: flex; flex-direction:row; min-width: 125px; align-items: center;"
        )
        //.attr('for', tableId+'checkbox_' + i)
        .attr("class", "material-checkbox")
        .attr("id", tableId + "checkbox_" + i);

      label.append(checkbox).append(span).append(features[i]);
      var cell = $("<td>").append(label);

      row.append(cell);
    }
    if (selectAllId) {
      $("#" + selectAllId).on("change", function () {
        const checked = this.checked;
        $table.find(".checkbox.individual").not(".target-feature").prop("checked", checked).trigger("change");
      });
    }
  }

  function createDistanceMetricsDropdown() {
    var dropdown = $("#class-imbalance-distance-dropdown");
    dropdown.empty(); // Clear previous options

    const distanceMetrics = [
      { value: "EU", label: "Euclidean Distance (EU)" },
      { value: "CH", label: "Chebyshev Distance (CH)" },
      { value: "KL", label: "Kullback-Leibler Divergence (KL)" },
      { value: "HE", label: "Hellinger Distance (HE)" },
      { value: "TV", label: "Total Variation Distance (TV)" },
      { value: "CS", label: "Chi-square Divergence (CS)" }
    ];

    distanceMetrics.forEach(metric => {
      var option = $("<option>")
        .attr("value", metric.value)
        .text(metric.label);
      dropdown.append(option);
    });
  }

});

function updateCrossDisable() {
  console.log("updateCrossDisable function called");
  // Get selected quasi-identifiers for each metric separately
  // This allows users to select the same feature for different metrics when appropriate
  const kAnonymityQIs = new Set();
  const lDiversityQIs = new Set();
  const tClosenessQIs = new Set();
  const entropyRiskQIs = new Set();
  const singleAttributeQIs = new Set();
  const multipleAttributeQIs = new Set();
  const classImbalanceFeatures = new Set();

  // Collect selected QIs for each metric independently
  $('input[name="quasi identifiers for k-anonymity"]:checked').each(
    function () {
      kAnonymityQIs.add($(this).val());
    }
  );

  $('input[name="quasi identifiers for l-diversity"]:checked').each(
    function () {
      lDiversityQIs.add($(this).val());
    }
  );

  $('input[name="quasi identifiers for t-closeness"]:checked').each(
    function () {
      tClosenessQIs.add($(this).val());
    }
  );

  $('input[name="quasi identifiers for entropy risk"]:checked').each(
    function () {
      entropyRiskQIs.add($(this).val());
    }
  );

  $(
    'input[name="quasi identifiers to measure single attribute risk score"]:checked'
  ).each(function () {
    singleAttributeQIs.add($(this).val());
  });

  $(
    'input[name="quasi identifiers to measure multiple attribute risk score"]:checked'
  ).each(function () {
    multipleAttributeQIs.add($(this).val());
  });

  // Collect selected features for class imbalance
  console.log("Looking for class imbalance checkboxes...");
  const allClassImbalanceCheckboxes = $('input[name="target features for class imbalance"]');
  console.log("Total class imbalance checkboxes found:", allClassImbalanceCheckboxes.length);
  const classImbalanceCheckboxes = $('input[name="target features for class imbalance"]:checked');
  console.log("Checked class imbalance checkboxes:", classImbalanceCheckboxes.length);
  classImbalanceCheckboxes.each(function () {
    const value = $(this).val();
    console.log("Adding class imbalance feature:", value);
    classImbalanceFeatures.add(value);
  });
  console.log("Class imbalance features set:", Array.from(classImbalanceFeatures));

  // Debug: Log all class imbalance checkboxes and their values
  allClassImbalanceCheckboxes.each(function(index) {
    console.log(`Checkbox ${index}: name="${$(this).attr('name')}", value="${$(this).val()}", checked=${$(this).is(':checked')}`);
  });

  // Get selected sensitive attributes for each metric
  const selectedSensitives = new Set();
  const sensitiveDropdowns = [
    "#lDiversitySensitiveDropdown",
    "#tClosenessSensitiveDropdown",
    "#allFeaturesDropdownMMS",
    "#allFeaturesDropdownMMM",
  ];

  sensitiveDropdowns.forEach((dropdownId) => {
    const selected = $(dropdownId).val();
    if (selected) selectedSensitives.add(selected);
  });

  // Check if main metric checkboxes are enabled
  const kAnonymityEnabled = $('input[name="k-anonymity"]').is(":checked");
  const lDiversityEnabled = $('input[name="l-diversity"]').is(":checked");
  const tClosenessEnabled = $('input[name="t-closeness"]').is(":checked");
  const entropyRiskEnabled = $('input[name="entropy risk"]').is(":checked");
  const singleAttributeEnabled = $(
    'input[name="single attribute risk score"]'
  ).is(":checked");
  const multipleAttributeEnabled = $(
    'input[name="multiple attribute risk score"]'
  ).is(":checked");
  const classImbalanceEnabled = $('input[name="class imbalance"]').is(":checked");

  // Update dropdowns - only disable options that are selected as QIs in the SAME metric
  // This prevents selecting the same feature as both QI and sensitive attribute within the same metric
  $("#lDiversitySensitiveDropdown option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", lDiversityQIs.has(val));
  });

  $("#tClosenessSensitiveDropdown option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", tClosenessQIs.has(val));
  });

  $("#allFeaturesDropdownMMS option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", singleAttributeQIs.has(val));
  });

  $("#allFeaturesDropdownMMM option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", multipleAttributeQIs.has(val));
  });

  // Update other metrics' dropdowns to disable features selected for class imbalance
  console.log("Disabling features in other dropdowns based on class imbalance selection...");
  $("#allFeaturesDropdownRepRate option").each(function () {
    const val = $(this).text();
    const shouldDisable = classImbalanceFeatures.has(val);
    if (shouldDisable) {
      console.log("Disabling feature in RepRate dropdown:", val);
    }
    $(this).prop("disabled", shouldDisable);
  });

  $("#allFeaturesDropdownStatRate1 option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", classImbalanceFeatures.has(val));
  });

  $("#allFeaturesDropdownStatRate2 option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", classImbalanceFeatures.has(val));
  });

  $("#allFeaturesDropdownRealRep option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", classImbalanceFeatures.has(val));
  });

  $("#all-features-dropdown-feature-relevance option").each(function () {
    const val = $(this).text();
    const shouldDisable = classImbalanceFeatures.has(val);
    if (shouldDisable) {
      console.log("Disabling feature in FeaRel dropdown:", val);
    }
    $(this).prop("disabled", shouldDisable);
  });

  $("#allFeaturesDropdownMMS option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", singleAttributeQIs.has(val) || classImbalanceFeatures.has(val));
  });

  $("#allFeaturesDropdownMMM option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", multipleAttributeQIs.has(val) || classImbalanceFeatures.has(val));
  });

  $("#allFeaturesDropdownCondDemoDis1 option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", classImbalanceFeatures.has(val));
  });

  $("#allFeaturesDropdownCondDemoDis2 option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", classImbalanceFeatures.has(val));
  });

  $("#lDiversitySensitiveDropdown option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", lDiversityQIs.has(val) || classImbalanceFeatures.has(val));
  });

  $("#tClosenessSensitiveDropdown option").each(function () {
    const val = $(this).text();
    $(this).prop("disabled", tClosenessQIs.has(val) || classImbalanceFeatures.has(val));
  });

  // Update QI checkboxes - only disable if selected as sensitive in the SAME metric
  // AND ensure they're disabled if the main metric checkbox is not checked
  // EXCLUDE feature relevance checkboxes from this logic
  $('input[name="quasi identifiers for k-anonymity"]').each(function () {
    const val = $(this).val();
    const isSelectedAsSensitive =
      $("#lDiversitySensitiveDropdown").val() === val;

    const shouldDisable = !kAnonymityEnabled || isSelectedAsSensitive;

    $(this).prop("disabled", shouldDisable);

    if (shouldDisable) {
      $(this).addClass("target-feature");
    } else {
      $(this).removeClass("target-feature");
    }
  });

  $('input[name="quasi identifiers for l-diversity"]').each(function () {
  const val = $(this).val();
  const isSelectedAsSensitive =
    $("#lDiversitySensitiveDropdown").val() === val;

  const shouldDisable = !lDiversityEnabled || isSelectedAsSensitive;

  $(this).prop("disabled", shouldDisable);

  if (shouldDisable) {
    $(this).addClass("target-feature");
  } else {
    $(this).removeClass("target-feature");
  }
});

$('input[name="quasi identifiers for t-closeness"]').each(function () {
  const val = $(this).val();
  const isSelectedAsSensitive =
    $("#tClosenessSensitiveDropdown").val() === val;

  const shouldDisable = !tClosenessEnabled || isSelectedAsSensitive;

  $(this).prop("disabled", shouldDisable);

  if (shouldDisable) {
    $(this).addClass("target-feature");
  } else {
    $(this).removeClass("target-feature");
  }
});


  $('input[name="quasi identifiers for entropy risk"]').each(function () {
    const val = $(this).val();
    $(this).prop("disabled", !entropyRiskEnabled);
  });

  $(
    'input[name="quasi identifiers to measure single attribute risk score"]'
  ).each(function () {
    const val = $(this).val();
    const isSelectedAsSensitive = $("#allFeaturesDropdownMMS").val() === val;
    $(this).prop("disabled", !singleAttributeEnabled || isSelectedAsSensitive);
  });

  $(
    'input[name="quasi identifiers to measure multiple attribute risk score"]'
  ).each(function () {
    const val = $(this).val();
    const isSelectedAsSensitive = $("#allFeaturesDropdownMMM").val() === val;
    $(this).prop(
      "disabled",
      !multipleAttributeEnabled || isSelectedAsSensitive
    );
  });

  // IMPORTANT: Feature relevance checkboxes should NEVER be disabled
  $('input[name="categorical features for feature relevancy"]:not(.target-feature), input[name="numerical features for feature relevancy"]:not(.target-feature)')
  .each(function () {
    $(this).prop("disabled", false);
  });
}

  // Update class imbalance feature checkboxes - disable if main metric checkbox is not checked
  $('input[name="target features for class imbalance"]').each(function () {
    $(this).prop("disabled", !classImbalanceEnabled);
  });

$(document).ready(function () {
  // Trigger when main metric checkboxes change
  $(document).on(
    "change",
    'input[name="k-anonymity"], input[name="l-diversity"], input[name="t-closeness"], input[name="entropy risk"], input[name="single attribute risk score"], input[name="multiple attribute risk score"], input[name="class imbalance"]',
    function () {
      updateCrossDisable();
    }
  );

  // Trigger when a QI checkbox changes - now each metric is independent
  $(document).on(
    "change",
    'input[name="quasi identifiers for k-anonymity"]',
    function () {
      updateCrossDisable();
    }
  );

  $(document).on(
    "change",
    'input[name="quasi identifiers for l-diversity"]',
    function () {
      updateCrossDisable();
    }
  );

  $(document).on(
    "change",
    'input[name="quasi identifiers for t-closeness"]',
    function () {
      updateCrossDisable();
    }
  );

  $(document).on(
    "change",
    'input[name="quasi identifiers for entropy risk"]',
    function () {
      updateCrossDisable();
    }
  );

  $(document).on(
    "change",
    'input[name="quasi identifiers to measure single attribute risk score"]',
    function () {
      updateCrossDisable();
    }
  );

  $(document).on(
    "change",
    'input[name="quasi identifiers to measure multiple attribute risk score"]',
    function () {
      updateCrossDisable();
    }
  );

  // Trigger when class imbalance feature checkboxes change
  $(document).on(
    "change",
    'input[name="target features for class imbalance"]',
    function () {
      console.log("Class imbalance feature checkbox changed:", $(this).val(), "checked:", $(this).is(":checked"));
      updateCrossDisable();
    }
  );

  // Trigger when any sensitive dropdown changes
  $(
    "#lDiversitySensitiveDropdown, #tClosenessSensitiveDropdown, #allFeaturesDropdownMMS, #allFeaturesDropdownMMM"
  ).on("change", function () {
    updateCrossDisable();
  });
});

function updateMetricCheckboxState(metricCheckboxName) {
  const metricCheckbox = document.querySelector(
    'input[type="checkbox"][name="' + metricCheckboxName + '"]'
  );
  if (metricCheckbox) {
    toggleValue(metricCheckbox);
  }
}



// Individual checkbox toggle for metric checkboxes
function toggleValueIndividual(checkbox) {
  const label = checkbox.closest("label");
  const text = label.textContent.trim();
  checkbox.value = text;
  console.log("Checkbox value:", checkbox.value); // For debugging
}
