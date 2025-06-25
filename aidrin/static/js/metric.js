// Slideshow control for the histograms

    // Thumbnail image controls
    function currentSlide(n) {
        showSlides(slideIndex = n);
      }
      function showSlides(n) {
        
        let lightMode = localStorage.getItem('darkmode') == "null";
        
        let slideContainerLight = document.getElementById("slideshow-container-light");
        let slideContainerDark = document.getElementById("slideshow-container-dark");
        let slidesLight = slideContainerLight.querySelectorAll(".mySlides");
        let slidesDark = slideContainerDark.querySelectorAll(".mySlides");

        let dots = document.getElementsByClassName("dot");
        if(lightMode){
            slideContainerLight.style.display = "block";
            slideContainerDark.style.display = "none";
        } else{
            slideContainerLight.style.display = "none";
            slideContainerDark.style.display = "block";
        }
        for (i = 0; i < slidesLight.length; i++) {
            slidesLight[i].style.display = "none";
            slidesLight[slideIndex-1].style.display = "block";
            slidesDark[i].style.display = "none";
            slidesDark[slideIndex-1].style.display = "block";
        }

        for (i = 0; i < dots.length; i++) {
          dots[i].className = dots[i].className.replace(" activeDot", "");
        }
        
        dots[slideIndex-1].className += " activeDot";
      }
      function clearDropdown(dropdownId) {
        var dropdown = document.getElementById(dropdownId);
        dropdown.selectedIndex = 0;
    
    }
    /* Toggles Dark Mode for Histogram Plots */
    const toggleSlidesColor = () => {
    const slidesLight = document.getElementById("slideshow-container-light");
    const slidesDark = document.getElementById("slideshow-container-dark");
    if(darkmode === "null") {
        slidesLight.style.display = "none";
        slidesDark.style.display = "block";
    }
    else {
        slidesLight.style.display = "block";
        slidesDark.style.display = "none";
    }

}
    /************ Taken out of metric data download pop up *************/
    function toggleVisualization(id) {
        var element = document.getElementById(id);
        if (element.style.display === 'none' || element.style.display === '') {
            element.style.display = 'block';
        } else {
            element.style.display = 'none';
        }
    }

    /** Error Handling: Creates a popup with error types and server response (details) */

    let errorPopup;
    function openErrorPopup(type,message){
        errorPopup = document.getElementById("error-popup");
        errorPopup.classList.add("open-popup");

        errorType = document.getElementById("error-type");
        errorType.innerHTML = "Error: "+type;

        errorMessage = document.getElementById("error-message");
        errorMessage.innerHTML = message;

        
    }
    function closeErrorPopup(){
        //error popup has to be present in the DOM for the function to call already
        errorPopup.classList.remove("open-popup");
    }
    // Catch resource loading errors by adding an event listener to the window
    window.addEventListener('error', function (e) {
        if (e.target && (e.target.tagName === 'IMG' || e.target.tagName === 'SCRIPT' || e.target.tagName === 'LINK')) {
            console.error("Resource failed to load:", e.target.src || e.target.href);
            openErrorPopup("Resource Load Error", `Failed to load ${e.target.tagName.toLowerCase()} from: ${e.target.src || e.target.href}`);
        }
    }, true); // useCapture=true is important for resource errors
    
    
$(document).ready(function () {
        fetch(retrieveFileUrl)
            .then(response => response.blob())  // Convert  to a Blob
            .then(fileBlob => {
                //append to form
                var formData = new FormData();
                formData.append('file', fileBlob, 'filename'); 

                

        $.ajax({
            url: '/feature_set',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function (response) {
                if (response.success) {

                    // Check if either categorical or numerical features exist in the response
                    if ('categorical_features' in response) {
                        createDropdown(response.categorical_features, 'catFeaturesDropdown');
                        createCheckboxContainer(response.categorical_features,'catFeaturesCheckbox1','categorical features for feature relevancy')
                    }

                    if ('numerical_features' in response) {
                        createDropdown(response.numerical_features, 'numFeaturesDropdownFeaRel');
                        createDropdown(response.numerical_features, 'numFeaturesDropdownPriv');
                        createCheckboxContainer(response.numerical_features,'numFeaturesCheckbox1','numerical features for feature relevancy')
                        createCheckboxContainer(response.numerical_features,'numFeaturesCheckbox2',"numerical features to add noise")
                    }

                    if ('all_features' in response){
                        createCheckboxContainer(response.all_features,'kAnonymityQIsCheckbox','quasi identifiers for k-anonymity');
                        updateMetricCheckboxState('k-anonymity');
                        createCheckboxContainer(response.all_features,'lDiversityQIsCheckbox','quasi identifiers for l-diversity');
                        createCheckboxContainer(response.all_features,'tClosenessQIsCheckbox','quasi identifiers for t-closeness');
                        createCheckboxContainer(response.all_features,'catFeaturesCheckbox2','quasi identifiers to measure single attribute risk score')
                        createCheckboxContainer(response.all_features,'catFeaturesCheckbox3','quasi identifiers to measure multiple attribute risk score')
                        createCheckboxContainer(response.all_features,'entropyRiskQIsCheckbox','quasi identifiers for entropy risk')
                        createDropdown(response.all_features,'allFeaturesDropdownRepRate');
                        createDropdown(response.all_features,'allFeaturesDropdownStatRate1');
                        createDropdown(response.all_features,'allFeaturesDropdownStatRate2');
                        createDropdown(response.all_features,'allFeaturesDropdownRealRep');
                        createDropdown(response.all_features,'allFeaturesDropdownFeaRel');
                        createDropdown(response.all_features,'allFeaturesDropdownClIm');
                        createDropdown(response.all_features,'allFeaturesDropdownMMS');
                        createDropdown(response.all_features,'allFeaturesDropdownMMM');
                        createDropdown(response.all_features,'allFeaturesDropdownCondDemoDis1');
                        createDropdown(response.all_features,'allFeaturesDropdownCondDemoDis2');
                        createDropdown(response.all_features, 'lDiversitySensitiveDropdown');
                        createDropdown(response.all_features, 'tClosenessSensitiveDropdown');
                        updateCrossDisable();
                    }
                    
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (error) {
                console.log(error);
                openErrorPopup("",error);
            }

        })
        .catch(error => {
            console.error('Error fetching file:', error)
            openErrorPopup("File Retrieval",error);
        });
    });

    function createDropdown(features, dropdownId) {
        var dropdown = $('#' + dropdownId);
        dropdown.empty(); // Clear previous options

        // Add default options
        dropdown.append($('<option value="" disabled>Select a Feature</option>'));

        // Populate the dropdown with options from the response
        
        for (var i = 0; i < features.length && features[0]!="{"; i++) {
            dropdown.append($('<option>').text(features[i]));
        }
    }
    


//generate summary statistics
$(document).ready(function () {
    document.getElementById('uploadForm').addEventListener('submit', function(event) {
        event.preventDefault(); // In order to prevent autoreload on sumbit, so that visualization data can be added.
    });

        var formData = new FormData();
        var file = "{{ url_for('retrieve_uploaded_file') }}";
        formData.append('file', file);
       
        $.ajax({
            url: '/summary_statistics',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function (response) {
                if (response.success) {
                    
                    $('#recordsCount').text(response.records_count);
                    $('#catFeatures').text(response.categorical_features);
                    $('#numFeatures').text(response.numerical_features);
                   

                    // Display additional summary statistics
                    
                    var statisticsHTML = '<h2 style="text-align:center">Summary Statistics Table</h2><table border="1">';
                    statisticsHTML += '<tr><th>Feature</th>'; // First column header

                    // Get statistic types (mean, median, etc.) from the first feature key
                    var firstKey = Object.keys(response.summary_statistics)[0]; 
                    var statKeys = Object.keys(response.summary_statistics[firstKey]);

                    // Create header row with stat names
                    statKeys.forEach(statKey => {
                        statisticsHTML += '<td class="statName">' + statKey + '</td>';
                    });
                    statisticsHTML += '</tr>'; // End header row

                    // Create rows for each feature (was previously a column)
                    for (var key in response.summary_statistics) {
                        statisticsHTML += '<tr><th><strong>' + key + '</strong></th>'; // Feature name as row header

                        // Fill in statistics for this feature
                        statKeys.forEach(statKey => {
                            statisticsHTML += '<td>' + response.summary_statistics[key][statKey] + '</td>';
                        });

                        statisticsHTML += '</tr>'; // End of row
                    }

                    statisticsHTML += '</table>';


                    statisticsHTML += '</table>';
                    
                    statisticsHTML += '<br><p id="Statresult" ><strong>Number of Features:</strong> <span id="featuresCount">' + response.features_count + '</span></p>';
                    statisticsHTML += '<p id="Statresult"><strong>Number of Data Points:</strong> <span id="recordsCount">' + response.records_count + '</span></p>';
                    statisticsHTML += '<p id="Statresult"><strong>Categorical Features:</strong> <span id="catFeatures">' + response.categorical_features + '</span></p>';
                    statisticsHTML += '<p id="Statresult"><strong>Numerical Features:</strong> <span id="numFeatures">' + response.numerical_features + '</span></p><br>';
                   
                    $('#summaryStatistics').html(statisticsHTML);
                    // Display histograms
                    var histogramsContainer = $('#histogramsContainer');
                    histogramsContainer.empty();
                    histogramsContainer.append('<br><h2 style="margin-top:0px;">Summary Statistic Plots</h2>'); // Add heading for histograms
    
                    var lightCount= 1;
                    var darkCount= 1;

                    var slideshow_container_light = $('<div id="slideshow-container-light" class="slideshow-container">');
                    var slideshow_container_dark = $('<div id="slideshow-container-dark" class="slideshow-container">');

                    for (var feature in response.histograms) {
                        var isLight = feature.includes('_light');
                
                        var base64Image = response.histograms[feature];
                        var img = document.createElement('img');
                        img.src = 'data:image/png;base64,' + base64Image;
                        img.alt = feature + ' Histogram';
                        // add theme class to the image
                        if (isLight) {
                            img.classList.add('light');
                        } else {
                            img.classList.add('dark');
                        }
                        /* Image carousel wrapper*/
                        let slideDiv = $('<div class="mySlides fade"></div>');
                        //show the first plot by default
                        
                        
                        slideDiv.append(img);
                        if(isLight){
                            
                            if(lightCount==1) slideDiv.css('display','block');
                            slideshow_container_light.append(slideDiv);
                            lightCount++;
                        } else{
                            if(darkCount==1) slideDiv.css('display','block');
                            slideshow_container_dark.append(slideDiv);
                            darkCount++;
                        }


                    }
                    let lightMode = localStorage.getItem('darkmode') == "null";
                    if(lightMode){
                        slideshow_container_light.css('display','block');
                        slideshow_container_dark.css('display','none');
                    } else{
                        slideshow_container_light.css('display','none');
                        slideshow_container_dark.css('display','block');
                    }
                    histogramsContainer.append(slideshow_container_light);
                    histogramsContainer.append(slideshow_container_dark);
                    /* dot switcher */
                    var dots = $('<div class="dots"></div>');
                    
                    
                    for(var j=1; j<lightCount; j++){
                        let dot = $('<span class="dot" onclick="currentSlide('+j+')"></span>');
                        dots.append(dot);
                        //darken the first by default
                       if(j==1){
                            dot.addClass('activeDot');
                        }
                    }
                    histogramsContainer.append(dots);
                    histogramsContainer.append('</div>');
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (error) {
                console.log(error);
                openErrorPopup("",error);
            }
        });
    });


//generate dropdown when features of the dataset are required to select
$(document).ready(function() {
       
        fetch(retrieveFileUrl)
        .then(response => {
            if (!response.ok) {
                throw new Error('File not found or server error');
            }
            return response.blob();  // Convert response to a Blob
        })
        .then(blob => {
            var reader = new FileReader();
            reader.onload = function(e) {
                var content = e.target.result;
                var lines = content.split('\n');
                if (lines.length > 0) {
                    var columns = lines[0].split(',');
                    console.log(columns);
                }
                createCheckboxContainer(columns,'correlationCheckboxContainer','all features for data transformation');
            };
            reader.readAsText(blob);
    
        });
});



function createCheckboxContainer(features, tableId, nameTag) {
    console.log(features)  
    var table = $('#' + tableId);
    table.empty(); // Clear previous content
    var columns = 4; // Maximum number of columns
    for (var i = 0; i < features.length && features[0]!="{"; i++) {
        if (i % columns === 0) {
            var row = $('<tr>');
            table.append(row);
        }

        var checkbox = $('<input>').attr({
            type: 'checkbox',
            class: 'checkbox individual',
            style: 'margin-right:10px',
            onchange: 'toggleValueIndividual(this)',
            id: tableId+'checkbox_' + i, // Generate unique ids so all buttons work
            name: nameTag, // Set the name attribute
            value: features[i],
            disabled: true
        });

        var span = $('<span>').addClass('checkmark');

        var label = $('<label>')
            // .attr('class','material-checkbox')
            .attr('style', 'display: flex; flex-direction:row; min-width: 125px; align-items: center;')
            //.attr('for', tableId+'checkbox_' + i)
            .attr('class', 'material-checkbox')
            .attr('id', tableId+'checkbox_' + i);

        label.append(checkbox).append(span).append(features[i]);
        var cell = $('<td>').append(label);

        row.append(cell);
    }
}
});
function updateCrossDisable() {
    const selectedQIs = new Set();
    $('input[name^="quasi identifiers"]').each(function () {
        if ($(this).is(':checked')) {
            selectedQIs.add($(this).val());
        }
    });

    const sensitiveDropdowns = ['#lDiversitySensitiveDropdown', '#tClosenessSensitiveDropdown','#allFeaturesDropdownMMS', '#allFeaturesDropdownMMM'];

    sensitiveDropdowns.forEach(dropdownId => {
        $(`${dropdownId} option`).each(function () {
            const val = $(this).text();
            if (selectedQIs.has(val)) {
                $(this).prop('disabled', true);
            } else {
                $(this).prop('disabled', false);
            }
        });
    });

    const selectedSensitives = new Set();
    sensitiveDropdowns.forEach(dropdownId => {
        const selected = $(dropdownId).val();
        if (selected) selectedSensitives.add(selected);
    });

    $('input[name^="quasi identifiers"]').each(function () {
        const val = $(this).val();
        if (selectedSensitives.has(val)) {
            $(this).prop('disabled', true);
        } else {
            if (!selectedQIs.has(val)) {
                $(this).prop('disabled', false);
            }
        }
    });
}
$(document).ready(function () {
  // Trigger when a QI checkbox changes
  $(document).on('change', 'input[name^="quasi identifiers"]', function () {
    updateCrossDisable();
  });

  // Trigger when any sensitive dropdown changes
  $('#lDiversitySensitiveDropdown, #tClosenessSensitiveDropdown, #allFeaturesDropdownMMS, #allFeaturesDropdownMMM').on('change', function () {
    updateCrossDisable();
  });
});

function updateMetricCheckboxState(metricCheckboxName) {
    const metricCheckbox = document.querySelector('input[type="checkbox"][name="' + metricCheckboxName + '"]');
    if (metricCheckbox) {
        toggleValue(metricCheckbox);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    updateMetricCheckboxState('k-anonymity');
    updateMetricCheckboxState('l-diversity');
    updateMetricCheckboxState('t-closeness');
    updateMetricCheckboxState('single attribute risk score');
    updateMetricCheckboxState('multiple attribute risk score');
    updateMetricCheckboxState('entropy risk');
    // ...add for all your metrics
});