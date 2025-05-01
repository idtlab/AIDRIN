/*
* ************************ FUNCTIONS MOVED FROM HTML PAGE ************************
*/
// Slideshow control for the histograms
    // Thumbnail image controls
    function currentSlide(n) {
        showSlides(slideIndex = n);
      }
      function showSlides(n) {
        let i;
        let slides = document.getElementsByClassName("mySlides");
        let dots = document.getElementsByClassName("dot");
        if (n > slides.length) {slideIndex = 1}
        if (n < 1) {slideIndex = slides.length}
        for (i = 0; i < slides.length; i++) {
          slides[i].style.display = "none";
        }
        for (i = 0; i < dots.length; i++) {
          dots[i].className = dots[i].className.replace(" activeDot", "");
        }
        slides[slideIndex-1].style.display = "block";
        dots[slideIndex-1].className += " activeDot";
      }
      function clearDropdown(dropdownId) {
        var dropdown = document.getElementById(dropdownId);
        dropdown.selectedIndex = 0;
        // Additional logic to clear dynamically added options if needed
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
    let errorPopup;
    document.addEventListener("DOMContentLoaded", function () {
        errorPopup = document.getElementById("error-popup");
    });
    function openErrorPopup(){
        errorPopup.classList.add("open-popup");
    }
    function closeErrorPopup(){
        errorPopup.classList.remove("open-popup");
    }
    
$(document).ready(function () {
        fetch(retrieveFileUrl)
            .then(response => response.blob())  // Convert  to a Blob
            .then(fileBlob => {
                //append to form
                var formData = new FormData();
                formData.append('file', fileBlob, 'filename'); 

                // Send the FormData via POST request
                fetch(window.location.href, {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => console.log('File uploaded successfully', data))
                .catch(error => console.error('Error:', error));

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
                        createCheckboxContainer(response.categorical_features,'catFeaturesCheckbox2','quasi identifiers to measure single attribute risk score')
                        createCheckboxContainer(response.categorical_features,'catFeaturesCheckbox3','quasi identifiers to measure multiple attribute risk score')
                        
                    }

                    if ('numerical_features' in response) {
                        createDropdown(response.numerical_features, 'numFeaturesDropdownFeaRel');
                        createDropdown(response.numerical_features, 'numFeaturesDropdownPriv');
                        createCheckboxContainer(response.numerical_features,'numFeaturesCheckbox1','numerical features for feature relevancy')
                        createCheckboxContainer(response.numerical_features,'numFeaturesCheckbox2',"numerical features to add noise")
                    }

                    if ('all_features' in response){
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
                    }
                    
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (error) {
                console.log(error);
            }

        })
        .catch(error => console.error('Error fetching file:', error));
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
                    histogramsContainer.append('<div class="slideshow-container">'); // Add container for the slideshow
                    var i = 1;
                    for (var feature in response.histograms) {
                        var base64Image = response.histograms[feature];
                        var img = document.createElement('img');
                        img.src = 'data:image/png;base64,' + base64Image;
                        img.alt = feature + ' Histogram';
                        /* Image carousel wrapper*/
                        let slideDiv = $('<div class="mySlides fade"></div>');
                        //show the first plot by default
                        if(i==1){
                            slideDiv.css('display','block');
                        }
                        i++;
                        slideDiv.append(img);
                        histogramsContainer.append(slideDiv);

                    }
                    /* dot switcher */

                    histogramsContainer.append('<div style="text-align:center">');
                    for(var j=1; j<i; j++){
                        histogramsContainer.append('<span class="dot" onclick="currentSlide('+j+')"></span>');
                        //darken the first by default
                       if(j==1){
                            $('.dot').addClass('activeDot');
                        }
                    }
                    histogramsContainer.append('</div></div>');
                } else {
                    alert('Error: ' + response.message);
                }
            },
            error: function (error) {
                console.log(error);
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
       
    var table = $('#' + tableId);
    table.empty(); // Clear previous content
    console.log("features:",features);
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
