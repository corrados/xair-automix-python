%*******************************************************************************
% Copyright (c) 2024-2024
% Author(s): Volker Fischer
%*******************************************************************************
% This program is free software; you can redistribute it and/or modify it under
% the terms of the GNU General Public License as published by the Free Software
% Foundation; either version 2 of the License, or (at your option) any later
% version.
% This program is distributed in the hope that it will be useful, but WITHOUT
% ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
% FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
% details.
% You should have received a copy of the GNU General Public License along with
% this program; if not, write to the Free Software Foundation, Inc.,
% 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA
%*******************************************************************************
function analyze()

close all;

channel_names = {'click', 'E-Git Mono', 'Stefan', 'Miguel', 'Chris', ...
  'E-Bass', 'E-Git L', 'E-Git R', 'A-Git', 'Kick', 'Snare', 'Tom1', 'Tom2', ...
  'Overhead', 'E-Drum L', 'E-Drum R'};

% read test data
h = fopen('test.dat', 'rb');
all_x = fread(h, Inf, 'int16');
fclose(h);

% create matrix with all the different input channels
all_x = reshape(all_x, 18, []) / 256; % scale to dB

for channel = 1:16
  analyze_channel(all_x, channel, channel_names{channel})
end

end

function analyze_channel(all_x, channel, name)

% analyze selected channel
hist_len = 100;
x = all_x(channel, :).';

hist_x = (0:99) * 129 / hist_len - 128; % according to xairautomix.py
hist_y = hist(x, hist_x);
hist_y = hist_y / max(hist_y) * 100; % convert to percent

index_value_above_threshold = find(hist_y > 0.05);
max_dB = hist_x(index_value_above_threshold(end));

% plot data
figure;
subplot(2, 1, 1); plot(x); grid on;
ylabel('dB'); title(['Input Level of Channel ' num2str(channel) ', ' name])
subplot(2, 1, 2); bar(hist_x, hist_y); xlim([-128, 0]); grid on;
xlabel('dB'); ylabel('%'); title(['Histogram, max ' num2str(max_dB) ' dB'])

end


